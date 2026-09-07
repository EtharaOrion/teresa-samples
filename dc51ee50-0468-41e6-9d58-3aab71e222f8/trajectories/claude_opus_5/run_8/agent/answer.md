I want to verify the deployment's collection interval and check how prometheus-rules tests run, since they likely use synthetic input series that wouldn't catch this mismatch. I'm also confirming the systemd_logs template ordering and that queryOptions.Limit=100 with OrderByDesc correctly returns the newest 100 rows since ordering happens before the limit is applied, then moving on to check the kubernetes_events template's projection.

A key finding: the exporter reads the timestamp from the first row off the channel, not the maximum. Since infraServiceLogs runs five concurrent queries feeding into one shared channel, that first row could come from any of them racing to arrive first — that's where cardinality collapses.

I'm also tracing through the timing config: collectionInterval is 2m, but CollectMetricValues won't refresh until 5m have passed, giving an effective 6m cycle, with a 60m cache TTL — meaning stale values could persist up to an hour after data stops flowing.

Critically, when a log source stops producing rows but the Kusto query still succeeds, that source's key won't appear in foundLogSources, so its cache entry never gets touched — the gauge freezes at its last value rather than resetting or growing. A low count like 300 would just sit there unchanged for up to an hour, which actively works against alerting rather than helping it. Now I have everything needed to write the final answer.
I have the complete chain traced end to end. Here is my analysis.

# Tracing `kusto_logs_age_in_seconds` from alert query to emitted series

## The two ends

**Consumer (the query text).** `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`, duplicated into the Bicep artifact at `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`:

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
for: 15m
```

**Producer (the series).** `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-43`:

```go
KustoLogsAgeInSecondsDesc = prometheus.NewDesc(
    "kusto_logs_age_in_seconds",
    "Age of last log in seconds from Kusto",
    []string{"kusto_cluster", "cluster", "table"}, nil)
```

## The dependency chain, file by file

1. `internal/cmd/serve.go:111,130-148` — one `collectLoop` goroutine per collector calls `CollectMetricValues` then sleeps `collectionInterval - duration`. Deployed value is `collectionInterval: "2m"` (`deploy/values.yaml:24`, wired at `deploy/templates/deployment.yaml:34`).
2. `kusto_logs_current.go:97` — a second, independent gate: `if c.lastRun.Add(KustoQueryInterval).After(startTime) { return }` with `KustoQueryInterval = 5 * time.Minute` (line 34). With a 2m loop, actual Kusto refresh is every ~6m.
3. `kusto_logs_current.go:101-112` — per `clusterName` in `c.clusterNames` (`--cluster-names={{ .svc.aks.name }},{{ .mgmt.aks.name }}`, i.e. `<env>-<region>-svc-1` and `<env>-<region>-mgmt-<stamp>` from `config/config.yaml:524,657`), builds `QueryOptions{InfraClusterName: clusterName, TimestampMin: now-120m, TimestampMax: now, Limit: 100, OrderBy: OrderByDesc}`.
4. `kusto_logs_current.go:129-139` — `GathererOptions{GatherInfraLogs: true}`, so `NewGatherer` sets `infraLogsOnly` (`gather.go:239`) and `GatherLogs` (`gather.go:331`) short-circuits into `gatherInfraLogs`.
5. `gather.go:533-563` — `gatherInfraLogs` runs exactly three definitions by name: `kubernetesEvents`, `systemdLogs`, then `serviceLogs(queryFactory, "infraServiceLogs", ...)`.
6. `kusto/templates/builtin/queries.yaml:1-12` — those three defs, none with `children`.
7. `kusto/query.go:300-311` — `Build` has no children, so `buildQuery(def.Name, ...)`; `query.go:263-269` stamps `name: def.Name` onto the `templateQuery`.
8. `kusto/client.go:154` — every row is emitted as `TaggedRow{Row: row, QueryName: query.GetName(), ...}`.
9. `gather.go:650` — `normalizedLogLine.QueryName = tagged.QueryName`.
10. `kusto_logs_current.go:117-127` — `key := logLine.QueryName`, first-write-wins into `foundLogSources[key] = logLine.Timestamp`.
11. `kusto_logs_current.go:147-157` — that same `logSource` string is passed as the **third label value**, i.e. `table`.

So `table` is not a Kusto table name at all — it is the *query definition name* from `queries.yaml`. The only three values this metric can ever carry are `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.

## Where the two ends are genuinely married up

Only `kusto_cluster` and `cluster` are honest. `kusto_cluster` is `c.kustoCluster` (from `--kusto-cluster={{ .kusto.kustoName }}`), and `cluster` is the AKS name the loop iterates. The alert's `cluster=~".*-svc-.*"` / `cluster!~".*-svc-.*"` discrimination therefore works: `<env>-<region>-svc-1` matches, `...-mgmt-<stamp>` does not. That branch is correctly wired.

## What makes a disagreement silent

**1. Case mismatch on `table="systemdlogs"`.** The producer emits `systemdLogs` (capital L, `queries.yaml:5`). The alert matches `systemdlogs` (all lowercase, three occurrences in both the YAML and the Bicep). PromQL label matching is byte-exact, and I confirmed there is no normalization anywhere in the chain — `grep -rn "ToLower\|ToUpper\|EqualFold"` across `tooling/aro-hcp-exporter/`, `tooling/hcpctl/pkg/kusto/`, `tooling/hcpctl/pkg/mustgather/` and `tooling/metricscache/` returns nothing, and there is no metric relabeling in `deploy/templates/servicemonitor.yaml`.

The consequence is not an error, it is a silent misrouting. `table="systemdlogs"` never matches anything, so the second and third disjuncts are permanently empty. Meanwhile `table!="systemdlogs"` matches `systemdLogs` — so systemd logs are silently swept into the strict 3600s branch and the deliberate 7200s allowance for svc clusters is dead code. Nothing errors; the rule just quietly evaluates the wrong branch.

**2. Cardinality collapse in `infraServiceLogs`.** `serviceLogs` (`mustgather/queries.go:43-57`) loops over the five `ServicesTables` (`containerLogs`, `clustersServiceLogs`, `fleetLogs`, `frontendLogs`, `backendLogs`) and builds five queries — but each one is built from the *same* definition, varying only `TemplateData.Table` via `WithTable` (`query.go:147`). `WithTable` touches only the rendered KQL, never the name. So all five `templateQuery` objects are named `infraServiceLogs`, all five rows carry `QueryName == "infraServiceLogs"`, and all five collapse onto one cache key and one series.

Worse, `queryclient.go:62-70` launches those five queries concurrently onto one shared `outputChannel`, and the exporter's `outputFunc` is first-write-wins (`if _, ok := foundLogSources[key]; !ok`). The single published `infraServiceLogs` value is therefore the freshness of whichever of the five tables won the race that cycle — not a max, not a min, and not stable between runs. Four of the five service tables can be entirely dead with no series and no alert.

**3. Absence is not alerted.** The expression is purely a `>` comparison with no `absent()` or `absent_over_time()` guard. If a query returns zero rows, no map key is created (lines 117-127 only fire per received row), so no series is produced. If `GatherLogs` fails outright, `kusto_logs_current.go:141-145` increments `exporter_collector_errors_total` and `continue`s — the previous cache entry is left untouched. Total ingestion failure looks identical to "nothing to report".

**4. Silent test agreement.** `observability/alerts/kusto-logs-age-prometheusRule_test.yaml` cannot catch any of this: it hand-writes its `input_series` with `table="ContainerLog"` and `table="systemdlogs"` — values the exporter can never emit. The promtool test asserts the rule against synthetic labels rather than against the producer's real label vocabulary, so the mismatch passes green.

## Why a stale value survives for a period once rows stop arriving

Three facts compose:

1. **The gauge is computed once and frozen.** `float64(time.Since(foundLogSources[logSource]).Seconds())` (line 153) is evaluated at write time. The `prometheus.Metric` handed to `cache.Set` is an immutable const metric. `Collect` (lines 88-91) just replays whatever is in the cache. So between refreshes the exported number does not tick upward — it is a constant, re-served on every 30s scrape (`servicemonitor.yaml`, `interval: 30s`).

2. **The cache TTL is 60 minutes.** `tooling/metricscache/cache.go` `GetAll` only drops an entry when `now.Sub(e.created) >= c.ttl`, and `created` is set at `Set` time. Deployed `cacheTTL: "60m"` (`values.yaml:23`) is an order of magnitude larger than the ~6m effective query interval.

3. **A quiet source is never overwritten and never deleted.** The update loop at lines 147-158 iterates over *found* sources only. A log source that returns no rows this cycle simply has no key in `foundLogSources`, so its stale cache entry is neither refreshed nor invalidated.

Net effect: when a table stops ingesting, its last-known age — say 300 seconds, comfortably under the 3600 threshold — is republished verbatim on every scrape for up to a full hour, then vanishes without ever crossing the threshold. Combined with the missing `absent()` guard and the `for: 15m`, ingestion can stop and the alert will never fire: first it is masked by the frozen healthy value, then it is masked by the series disappearing. The 60m TTL is actively anti-alerting here, not merely a lag.

## What would need to change (not applied — read-only investigation)

- Align the case: either emit `systemdlogs` from `logSource` at `kusto_logs_current.go:156`, or change `systemdlogs` → `systemdLogs` in the three places in `kusto-logs-age-prometheusRule.yaml` and the mirrored Bicep expression. Changing the alert side is lower blast radius; changing the exporter side would orphan any existing dashboards keyed on the current value.
- Give the five `ServicesTables` distinct label values — plumb the `TemplateData.Table`/`WithTable` value through `templateQuery`, `TaggedRow` and `NormalizedLogLine` so `table` reflects the real Kusto table, rather than reusing `QueryName`.
- Add an `absent()`-style companion alert, or have the collector emit an explicit zero/sentinel series for configured-but-empty sources, so silence is distinguishable from health.
- Reduce `cacheTTL` to a small multiple of the effective query interval (it is currently 10x), so a stalled source ages out promptly instead of being republished frozen for an hour.

I made no modifications to the repository; the working tree is unchanged.