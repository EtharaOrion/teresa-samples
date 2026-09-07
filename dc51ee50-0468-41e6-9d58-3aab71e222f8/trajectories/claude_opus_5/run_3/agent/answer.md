The working tree looks clean, so I can move on to writing the final answer now.

# `kusto_logs_age_in_seconds`: full dependency chain, alert ↔ series

Read-only investigation. Working tree verified clean (`git status --porcelain` returns nothing).

## 1. The two ends

**Consumer (the query text).** `observability/alerts/kusto-logs-age-prometheusRule.yaml:12-21`, alert `KustoLogsDataStale`, `for: 15m`, group `kusto-logs-age-rules` with group label `component: kusto`:

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
```

It is pulled into the bundle by `observability/alerts-sl-services.yaml:16` and rendered into Azure Managed Prometheus at `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2192,2223`. Unit tests live in `observability/alerts/kusto-logs-age-prometheusRule_test.yaml` and are executed by `promtool test rules` (`tooling/prometheus-rules/internal/generator.go:325`).

**Producer (the series).** `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:37-43` declares the `*prometheus.Desc` with variable labels `[]string{"kusto_cluster", "cluster", "table"}` and no const labels; `:149-156` constructs the sample.

## 2. The chain, label by label

**`kusto_cluster`** — `c.kustoCluster` (set `kusto_logs_current.go:72`) ← `NewKustoLogsCurrentCollector(o.KustoCluster, …)` (`internal/cmd/options.go:200`) ← `--kusto-cluster` (`options.go:158`) ← `deploy/templates/deployment.yaml:36` ← `deploy/values.yaml:28 kustoCluster: "{{ .kusto.kustoName }}"` ← `config/config.yaml:342` (`hcp-{env}-{geoShortId}`). The same string also builds the query endpoint via `kusto.KustoEndpoint` (`kusto_logs_current.go:61`), so the label genuinely names the cluster that was queried.

**`cluster`** — the loop variable `clusterName` over `c.clusterNames` (`kusto_logs_current.go:101`) ← `--cluster-names` ← `deploy/values.yaml:26 clusterNames: "{{ .svc.aks.name }},{{ .mgmt.aks.name }}"` ← `config/config.yaml:524` (`{env}-{region}-svc-1`) and `:657` (`{env}-{region}-mgmt-{stamp}`). The *same* value is pushed into `QueryOptions.InfraClusterName` (`:107`), flows through `NewTemplateDataFromOptions` → `WithClusterName` → `kqlEscStr` (`hcpctl/pkg/kusto/query.go:177-181,106-108`) and lands in `| where cluster == '{{.ClusterName}}'` in each template. **This end is genuinely married up**: the label equals the KQL filter, and the alert's `.*-svc-.*` discriminator matches the real AKS naming convention. It also matches the `cluster` column Arobit stamps at ingestion (`observability/arobit/deploy/templates/forwarder-configmap.yaml:183,190` ← `values-svc.yaml:10` / `values-mgmt.yaml:10`), which is the same config value — so producer, ingester and alert all agree here.

**`table`** — this is where the marriage breaks. `kusto_logs_current.go:119` does `key := logLine.QueryName`, and that key is passed as the third label value at `:155`. `QueryName` is not a table name: `kusto/client.go:154` tags every row with `query.GetName()`, i.e. the `name:` field of the YAML query definition (`kusto/query.go:63-65`, `query_definitions.go:6`). Because the collector sets `GatherInfraLogs: true` (`kusto_logs_current.go:130`), `GatherLogs` short-circuits to `gatherInfraLogs` (`mustgather/gather.go:331-334`), which runs exactly three definitions from `kusto/templates/builtin/queries.yaml`: `kubernetesEvents`, `systemdLogs`, `infraServiceLogs` (`gather.go:533,545,557`). So the only `table` values the exporter can ever emit are those three literal strings.

## 3. Where the two ends silently disagree

**(a) Case mismatch — two of three disjuncts are dead.** The exporter emits `systemdLogs` (camelCase, from `queries.yaml:5`). The alert matches `table="systemdlogs"` (all lowercase), and every fixture in `kusto-logs-age-prometheusRule_test.yaml:38,47,68` uses the lowercase spelling too. PromQL label matching is byte-exact, so disjuncts 2 and 3 never select anything in production. The failure is silent because an empty vector from a label matcher is perfectly legal — no parse error, no `promtool` failure (the tests fabricate their own series and so validate the *rule against itself*, never against a real exporter sample). The visible consequence: systemd logs are still caught, but by disjunct 1 (`table!="systemdlogs"` is true for `systemdLogs`), meaning svc clusters are held to 3600s and the deliberate 7200s carve-out for `cluster=~".*-svc-.*"` is unreachable code.

**(b) `infraServiceLogs` collapses five tables into one series.** `serviceLogs` (`mustgather/queries.go:43-57`) loops over `ServicesTables = {containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs}` (`queries.go:22-27`) and builds one query per table via `WithTable`, but every one of the five reuses `def.Name` — `Build` only renames when `def.Children` is non-empty (`kusto/query.go:296-312`), and `infraServiceLogs` has no children. All five therefore report `GetName() == "infraServiceLogs"`. They execute concurrently into a single channel (`queryclient.go:62-83`), and `kusto_logs_current.go:120-122` keeps only the first arrival per key (`if _, ok := foundLogSources[key]; !ok`). One healthy table masks four stalled ones, and which one wins is a scheduling race. The alert's `{{ $labels.table }}` annotation then names a query, not the table that is actually behind.

Note also that neither the test fixtures nor the alert use the strings the exporter actually produces: fixtures use `ContainerLog`, which the exporter never emits.

## 4. Why a stale value survives for a period once rows stop arriving

The producer is write-only-on-success and has no negative signal:

1. `outputFunc` (`kusto_logs_current.go:117-127`) only records a timestamp for query names that returned at least one row. If a table stops ingesting, its key is simply absent from `foundLogSources`.
2. The publish loop `for logSource := range foundLogSources` (`:146`) therefore performs **no `Set`** for that source. There is no zero-fill, no tombstone, no "last seen empty" bookkeeping. A query returning zero rows and a query never having been asked are indistinguishable downstream.
3. Serving is decoupled from collection. `Collect` (`:88-91`) just replays `c.cache.GetAll()`. In `tooling/metricscache/cache.go`, `Set` stamps `created: time.Now()` (`:52-56`) and `GetAll` evicts only when `now.Sub(e.created) >= c.ttl` (`:59-71`). So every scrape re-serves the *frozen* `MustNewConstMetric` — a constant, not a recomputed age. The value does not grow with wall-clock time.
4. Duration of the lie: `--cache-ttl` is `60m` (`deploy/values.yaml:23`), so a stale-but-fresh-looking value is republished for up to a full hour after the last successful row. Then the entry is deleted and the series simply *disappears*.

Two amplifiers:

- **Nothing alerts on disappearance.** There is no `absent()` rule for `kusto_logs_age_in_seconds` anywhere in `observability/` (only the upstream control-plane rules and `arobit`/`prometheus` use that pattern). A totally dead pipeline ends as no series at all, which `> 3600` cannot fire on.
- **The value can never grow past its own ceiling.** `TimestampMin = now-120m` (`:108`) bounds the newest row the query can find, so the age is capped near 7200s and, more importantly, once ingestion stops the query returns nothing rather than an ever-older row. The alert wants a *rising* number; the design can only ever give a frozen one or nothing.
- **Errors are quiet too.** On gather failure the code increments `c.errorCounter` and `continue`s (`:141-145`), leaving the previous cached metric in place. `exporter_collector_errors_total` (`internal/cmd/serve.go:38-44`) is exposed but no alert in the repo consumes it.

One more inconsistency worth flagging: `--kusto-query-interval` is defined and threaded through `RawOptions`/`ValidatedOptions` (`options.go:48,64,78,120,160`) but is **never passed to** `NewKustoLogsCurrentCollector` (`options.go:200`) and never stored on the collector. The self-throttle at `kusto_logs_current.go:97` reads the package constant `KustoQueryInterval = 5 * time.Minute` directly, so the flag is inert. Combined with `--collection-interval=2m`, roughly every other collection loop is a no-op.

## 5. What would need to change (not applied)

- Align the spelling: either lowercase the emitted label or fix the two `table="systemdlogs"` matchers (and the fixtures) to `systemdLogs`. Changing one side without the other keeps the disagreement.
- Give `infraServiceLogs` per-table identity — carry the concrete table on `TaggedRow`/`NormalizedLogLine`, or give the definition `children` so `Build` assigns distinct names — and replace the first-wins `!ok` guard with latest-wins so a healthy table cannot mask a stalled one.
- Emit an explicit staleness marker when a query returns zero rows (publish a sentinel age or a `_last_success_timestamp` gauge) instead of relying on cache decay, and/or add an `absent()`/`exporter_collector_errors_total` alert so vanished series are not silent.
- Pass `o.KustoQueryInterval` into the collector so the flag stops being inert.

I made no edits; the deliverable is this analysis.