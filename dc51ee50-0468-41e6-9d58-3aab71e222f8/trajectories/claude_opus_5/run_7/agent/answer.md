I have traced the complete chain. Here is what the code actually does.

## The chain, end to end

**1. The query text** — `tooling/hcpctl/pkg/kusto/templates/builtin/queries.yaml` declares three definitions that the exporter path reaches, each with a `name` and a `templatePath`:

- `kubernetesEvents` → `infra/kubernetes_events.kql.gotmpl` (hardcodes table `kubernetesEvents`)
- `systemdLogs` → `infra/systemd_logs.kql.gotmpl` (hardcodes table `systemdLogs`)
- `infraServiceLogs` → `infra/service_logs.kql.gotmpl`, whose first line is the template variable `{{.Table}}`

**2. Table substitution** — `mustgather/queries.go:43-56` (`serviceLogs`) loops over `ServicesTables` = `containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs` and calls `f.Build(*def, ...kusto.WithTable(table)...)` once per table. `WithTable` (`kusto/query.go:147`) only sets `TemplateData.Table`, which is interpolated into the KQL body.

**3. Naming** — `QueryFactory.Build` → `buildQuery(def.Name, ...)` (`kusto/query.go:294-302`) stamps `name: def.Name` on every produced `templateQuery`. `def.Name` does not vary with `TemplateData.Table`. So all five per-table queries are named `infraServiceLogs`.

**4. Tagging** — `kusto/client.go:154` emits `TaggedRow{Row: row, QueryName: query.GetName(), ...}`. `mustgather/gather.go:650` copies it: `normalizedLogLine.QueryName = tagged.QueryName`.

**5. Reduction to a label** — `kusto_logs_current.go:117-127`:
```
key := logLine.QueryName
if _, ok := foundLogSources[key]; !ok { foundLogSources[key] = logLine.Timestamp }
```
**6. Publication** — lines 146-158: `key := fmt.Sprintf("%s/%s/%s", c.kustoCluster, clusterName, logSource)` and `MustNewConstMetric(KustoLogsAgeInSecondsDesc, GaugeValue, time.Since(...).Seconds(), c.kustoCluster, clusterName, logSource)` against `[]string{"kusto_cluster", "cluster", "table"}` (line 41).

**So the `table` label is the query *definition name*, never the Kusto table name.** The only values this exporter can ever emit are `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.

## Where the two ends are genuinely married up

Only `cluster` and `kusto_cluster` are honestly joined: `clusterNames` comes from Helm `values.yaml` (`clusterNames: "{{ .svc.aks.name }},{{ .mgmt.aks.name }}"`), which is why the alert's `cluster=~".*-svc-.*"` discrimination works. `kusto_cluster` is `.kusto.kustoName`. Both are passed straight through `options.go:200` into the collector and out as label values unmodified.

## What makes the disagreement silent

`observability/alerts/kusto-logs-age-prometheusRule.yaml:13` selects on `table="systemdlogs"` and `table!="systemdlogs"`. The exporter emits `systemdLogs`. **Prometheus label matching is case-sensitive**, so `table="systemdlogs"` matches nothing, and every real series falls into the `table!="systemdlogs"` arm at the 3600s threshold. The two special-cased branches (the 7200s allowance for `-svc-` management clusters) are dead code.

Nothing catches this because the three artifacts are decoupled:
- The label value is built from a Go struct field, while the alert is a YAML string. There is no shared constant, no schema, no generation step tying `QueryDefinition.Name` to the rule expression.
- The unit test `kusto-logs-age-prometheusRule_test.yaml` supplies its own `input_series` with invented values — `table="ContainerLog"` (which the exporter never emits in any casing) and `table="systemdlogs"`. Because the fixture *asserts* the vocabulary rather than *importing* it, the test passes green while the production vocabulary is different. It is testing that PromQL works, not that the exporter and the rule agree.
- There are no tests at all under `tooling/aro-hcp-exporter/internal/metrics/`, so nothing pins the emitted label values from the other side either.
- A label selector that matches zero series yields an empty vector, not an error, so `promtool` and Prometheus both stay quiet.

A second silent disagreement sits upstream: because `Build` ignores `TemplateData.Table` when naming, the five `ServicesTables` queries are launched concurrently (`queryclient.go:62-84`, `errgroup`) into one shared `queryOutputChannel` and all tag rows `infraServiceLogs`. The `if _, ok := ...; !ok` guard keeps the *first arriving* row, so five distinct log sources collapse into a single series whose value is whichever table's goroutine won the race that cycle. `containerLogs` going silent is invisible if `frontendLogs` is healthy, and the value can jump between tables run to run.

Related: `--kusto-query-interval` is parsed into `RawOptions`/`ValidatedOptions` (`options.go:48,78,120,160`) but `CompletedOptions` never carries it and `NewKustoLogsCurrentCollector` never takes it — line 97 uses the package constant `KustoQueryInterval`. Setting the flag does nothing.

## Why a stale value survives after rows stop arriving

Three mechanisms compound:

**The gauge is frozen, not recomputed.** `MustNewConstMetric` bakes the float in at `Set` time. `Collect` (lines 89-93) merely re-emits the cached `prometheus.Metric`. Every scrape between two collection cycles returns the identical number, and since const metrics carry no explicit timestamp, Prometheus stamps them at scrape time — a stale reading is indistinguishable from a fresh one.

**The cache is set-only; absence never deletes.** `metricscache.Cache.Set` overwrites and resets `created`; nothing removes a key when a log source stops reporting. If `foundLogSources` no longer contains a source, the loop at line 146 simply never touches it. Eviction happens only lazily in `GetAll`, when `now.Sub(e.created) >= c.ttl`. With `cacheTTL: "60m"` from `values.yaml`, a series persists for up to a full hour after its last successful observation, serving the frozen value the whole time.

**The query window caps the value, then hides it.** `queryOptions.TimestampMin = time.Now().Add(-120 * time.Minute)` with `OrderByDesc` and `Limit = 100`. While ingestion lags under two hours, the newest row is still in-window and the age climbs. Once the newest row falls outside 120 minutes, the query returns zero rows, `foundLogSources` has no key, no `Set` occurs — and 60 minutes later the series *disappears* rather than exceeding the threshold. Combined with `for: 15m`, total outages can silence the alert instead of firing it, while the last thing published is a plausible-looking sub-threshold number.

Also note `c.lastRun = time.Now()` (line 160) executes after the cluster loop regardless of failures; the `continue` on line 144 skips a failing cluster but still advances the clock, so a cluster erroring is not retried for a full `KustoQueryInterval`. It only increments `errorCounter`.

## What would need to change

I made no edits. To fix this you would need to (a) propagate the table into the query identity — either add a `Table`/label field to `templateQuery` populated from `TemplateData.Table` and use it for the metric label instead of `QueryName`, or give each per-table query a distinct name in `serviceLogs`; (b) reconcile the casing between the emitted values and the rule expression, ideally by driving the rule from the same source as `queries.yaml` rather than hand-writing it; (c) make the alert-rule fixture use values the exporter can actually produce; and (d) decide explicitly whether a vanished series should alert (`absent()`/`absent_over_time()`) rather than resolving silently.

I have verified the entire chain. Here is my analysis.

# `kusto_logs_age_in_seconds`: query text → labels → published value

Read-only investigation. Nothing changed; `git status` is clean.

## The dependency chain, file by file

**1. Query text is declared** — `tooling/hcpctl/pkg/kusto/templates/builtin/queries.yaml`. Three definitions are reachable on the exporter path (`name` → `templatePath`):
- `kubernetesEvents` → `infra/kubernetes_events.kql.gotmpl` (hardcodes table `kubernetesEvents`)
- `systemdLogs` → `infra/systemd_logs.kql.gotmpl` (hardcodes table `systemdLogs`)
- `infraServiceLogs` → `infra/service_logs.kql.gotmpl`, whose first pipeline line is the placeholder `{{.Table}}`

**2. The table is substituted, then discarded** — `mustgather/queries.go:21-27` defines `ServicesTables = {containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs}`. `serviceLogs()` (line 43) loops over all five, calling `f.Build(*def, kusto.NewTemplateDataFromOptions(options, kusto.WithTable(table), ...))`. `WithTable` (`kusto/query.go:147-151`) sets `TemplateData.Table`, which renders into the KQL body only.

**3. Naming collapses the fan-out** — `QueryFactory.Build` / `buildQuery` (`kusto/query.go:244-262`, `293+`) sets `name: def.Name`. `def` is the *same* `infraServiceLogs` definition on every iteration, and `TemplateData.Table` is never consulted for the name. **All five queries are born with the identical name `infraServiceLogs`.** That is the exact point where the table identity is lost.

**4. Tagging** — `kusto/client.go:154`: `TaggedRow{Row: row, QueryName: query.GetName(), ...}`. `mustgather/gather.go:650`: `normalizedLogLine.QueryName = tagged.QueryName`.

**5. Reduction to a label** — `kusto_logs_current.go:117-127`, the exporter's `outputFunc`:
```go
key := logLine.QueryName
if _, ok := foundLogSources[key]; !ok {
        foundLogSources[key] = logLine.Timestamp   // first row wins
}
```
Because `queryOptions.OrderBy = OrderByDesc` (line 112), the first row per key is the newest — the intended semantic, but only per *name*.

**6. Publication** — lines 147-157: `key := fmt.Sprintf("%s/%s/%s", c.kustoCluster, clusterName, logSource)` and `MustNewConstMetric(KustoLogsAgeInSecondsDesc, GaugeValue, time.Since(...).Seconds(), c.kustoCluster, clusterName, logSource)`, positionally bound to `[]string{"kusto_cluster","cluster","table"}` (line 41).

## Where the two ends are genuinely married up

Only `cluster` and `kusto_cluster`. `clusterNames` flows from Helm `values.yaml:26` (`{{ .svc.aks.name }},{{ .mgmt.aks.name }}`) → `--cluster-names` (`deployment.yaml:37`) → `options.go:200` → the `table` label's sibling. That is why the alert's `cluster=~".*-svc-.*"` discrimination genuinely works. `kusto_cluster` is `.kusto.kustoName` and is likewise faithful.

## What makes a disagreement silent

**The `table` label is the query *definition name*, never a Kusto table name.** The only three values this exporter can emit are `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.

The alert (`observability/alerts/kusto-logs-age-prometheusRule.yaml:13`) selects on `table="systemdlogs"` and `table!="systemdlogs"`. Prometheus label matching is case-sensitive, and the emitted value is `systemdLogs`. So the `table="systemdlogs"` arms are **permanently empty**, and every real systemd series falls into the `table!="systemdlogs"` arm at the 3600s threshold. The deliberate 7200s allowance for `-svc-` clusters is unreachable. Nothing errors — a selector that matches nothing is a valid, silent empty vector.

The disagreement is invisible because the fixture `kusto-logs-age-prometheusRule_test.yaml` invents its own input series (`table="ContainerLog"`, `table="systemdlogs"`) rather than deriving them from the exporter. The tests pass while asserting on label values the exporter cannot produce. There is no exporter-side test at all (`internal/metrics/` has no `_test.go`), so no test on either side ever compares emitted labels against consumed labels.

Compounding this: all five service-log tables share the key `infraServiceLogs`, so per-cluster they produce **one** series whose value is whichever table's row arrived first. `ConcurrentQueries` (`queryclient.go:62-84`) runs the five queries in parallel `errgroup` goroutines writing into one channel, so the winner is a genuine race. Consequences: `containerLogs` going silent is masked whenever `frontendLogs` is healthy, and the published value can jump between tables run to run with no label change to explain it.

## Why a stale value survives once rows stop arriving

Two independent mechanisms:

**The value is frozen, not recomputed.** `MustNewConstMetric` bakes the float in at `Set` time. `Collect` (lines 89-93) merely re-emits the cached `prometheus.Metric` on every scrape. Between refreshes the reported age is constant, even though real age grows continuously — it is a 5-minute staircase, not a ramp.

**The cache is set-only.** `metricscache.Cache` (`tooling/metricscache/cache.go`) exposes only `Set` and `GetAll`. If a log source stops producing rows, `foundLogSources` simply has no entry, so the loop at line 147 never touches its key. The only removal is passive expiry in `GetAll`: `if now.Sub(e.created) >= c.ttl { delete }`. Note `created` is reset on every `Set`, so it is a write-age TTL, not a data-age TTL. With `cacheTTL: "60m"` (`values.yaml:23`), a dead log source keeps re-exporting its last frozen value for up to **60 minutes**, then vanishes rather than rising — so `> 3600` may never fire.

Three further amplifiers:
- Line 97 rate-limits to `KustoQueryInterval` (5m) regardless of the 2m `collectionInterval`, so most invocations are no-ops.
- Line 141-144: on `GatherLogs` error the code increments `errorCounter` and `continue`s, leaving the whole cluster's stale entries intact and refreshing nothing.
- Line 108 bounds the lookback to `-120 * time.Minute`. A source silent longer than 2h returns zero rows, so it can never report an age above ~7200s — it disappears instead. Combined with the 60m TTL, the observable age is capped well below what a long outage deserves.

## Would-be fixes (described, not applied)

1. Carry the table into identity: give `templateQuery` a table field (or have `serviceLogs` build a distinct per-table name) and populate the `table` label from it rather than from `QueryName`.
2. Reconcile casing between emitted values and the rule expression, treating `queries.yaml` names as the source of truth.
3. Rebuild the alert fixture from values the exporter can actually emit, and add an exporter-side test asserting the emitted label set — that is the missing link that let the mismatch persist.
4. Detect disappearance explicitly (`absent_over_time`), since this exporter signals outages by omission rather than by a rising value.

Items 1 and 2 are alternatives at different layers: fixing the label to real table names would also require rewriting the rule, so they should be decided together.