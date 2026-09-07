# The dependency chain from alert text to published series

I traced `kusto_logs_age_in_seconds` end to end. Two of its three labels are genuinely married to the query; the third is not, and that is where the disagreement lives.

## The chain, file by file

**1. The query text (the consumer).**
`observability/alerts/kusto-logs-age-prometheusRule.yaml:13`:
```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
```
with `for: 15m`. The same expression is mirrored into `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`, so both the Kubernetes and the Azure Monitor rule share the assumption.

**2. The contract.** `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38` declares the Desc with `[]string{"kusto_cluster", "cluster", "table"}`.

**3. Where the values are written** (same file, ~147–158):
```go
key := fmt.Sprintf("%s/%s/%s", c.kustoCluster, clusterName, logSource)
c.cache.Set(key, prometheus.MustNewConstMetric(
    KustoLogsAgeInSecondsDesc, prometheus.GaugeValue,
    float64(time.Since(foundLogSources[logSource]).Seconds()),
    c.kustoCluster, clusterName, logSource))
```
`logSource` is simultaneously the `table` label and the last cache-key segment.

**4. Where `logSource` comes from** (~116–123): `key := logLine.QueryName; foundLogSources[key] = logLine.Timestamp`.

**5. What `QueryName` actually is.** `mustgather/gather.go:650` → `kusto/client.go:154` (`QueryName: query.GetName()`) → `templateQuery.name` → `buildQuery(name, ...)` → `Build()` uses `def.Name` (or `child.Name` when a definition has `children`). **It is the query-definition name, never a Kusto table name.**

**6. What the exporter runs.** It passes `GatherInfraLogs: true`, so `gatherInfraLogs` (`gather.go:527`) runs three stages: `kubernetesEvents`, `systemdLogs`, and `serviceLogs(queryFactory, "infraServiceLogs", ...)`. In `mustgather/queries.go:43` that last call loops over `ServicesTables` = `containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs`, calling `Build(*def, ...WithTable(table)...)` against the **single** `infraServiceLogs` definition, which has no `children:` in `templates/builtin/queries.yaml`.

## Where the two ends are genuinely married up

`cluster` and `kusto_cluster` are safe by construction. `queryOptions.InfraClusterName = clusterName` flows through `NewTemplateDataFromOptions` → `WithClusterName` → `{{.ClusterName}}` in the KQL `| where cluster == '...'`, and the *same* `clusterName` variable is passed as the label. Likewise `c.kustoCluster` both builds the endpoint URL in `KustoEndpoint` and becomes the label. One variable, two uses — they cannot drift.

## Where they are not

`WithTable(table)` (`query.go:147`) only substitutes `{{.Table}}` in `infra/service_logs.kql.gotmpl`. It never touches the query's name. So the *query text* varies across five tables while the *name* is constant. The label and the query body are drawn from **two different fields of the same `Build()` call**, and nothing reconciles them.

The only `table` values the exporter can ever emit are three: `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`. Consequences:

- **Five tables collapse into one series.** All five write `foundLogSources["infraServiceLogs"]` and then the same cache key. `ConcurrentQueries` (`queryclient.go:62`) runs them as parallel goroutines into one channel, so the survivor is arbitrary. One healthy table masks four dead ones.
- **The overwrite has no `max`.** Line 121 assigns unconditionally, and the queries use `OrderByDesc` with `Limit = 100`. Rows arrive newest-first, so the value that survives is the *oldest* row of the fetched window, not the newest — the age is systematically overstated even in the happy path.
- **Case mismatch.** Emitted `systemdLogs` vs. queried `systemdlogs`. PromQL label matching is exact and case-sensitive, so `table="systemdlogs"` matches nothing; both systemd branches are dead code and the `-svc-` 7200 relaxation never applies. Worse, `table!="systemdlogs"` matches *every* series including `systemdLogs`, so the first disjunct silently swallows them at the stricter 3600 threshold.

## What makes the disagreement silent

Nothing validates label *values*. `MustNewConstMetric` only checks label *cardinality* — three strings are three strings, so a wrong one panics nothing and logs nothing.

The alert unit test is the part that should have caught it and instead conceals it: `kusto-logs-age-prometheusRule_test.yaml` feeds hand-written fixtures with `table="ContainerLog"` and `table="systemdlogs"`. Neither string is producible by the exporter (`ContainerLog` is not even in `ServicesTables`, which spells it `containerLogs`). The test asserts the PromQL against invented input, so it is green while the rule cannot match production data. There is no contract test tying `KustoLogsAgeInSecondsDesc`'s emitted values to the rule's matchers.

## Why a stale value survives, then vanishes without alerting

Four mechanisms compound, and the net effect is the opposite of the alert's intent:

1. **Absence is not zero, and not an update.** If a source stops producing rows, `outputFunc` never sees that `QueryName`, so `foundLogSources` has no entry and `cache.Set` is never called for that key. The old entry is neither refreshed nor removed.
2. **The value is frozen, not growing.** The cache stores a fully-built `MustNewConstMetric` whose age was computed with `time.Since(...)` at write time. `Collect` just replays `c.cache.GetAll()`. So the series keeps reporting the *same* number rather than climbing toward 3600.
3. **The survival window is 60 minutes.** `metricscache/cache.go:65` evicts only when `now.Sub(e.created) >= c.ttl`, and the deployed `cacheTTL` is `"60m"` (`deploy/values.yaml`), far above the `DefaultCacheTTL = 1 * time.Minute`.
4. **Refresh is rarer than it looks.** `CollectMetricValues` early-returns while `c.lastRun.Add(KustoQueryInterval).After(startTime)`, and `KustoQueryInterval` is a hard-coded `5 * time.Minute` even though the deployed `collectionInterval` is `"2m"` — so most loop ticks are no-ops.

So when ingestion dies, the series holds its last healthy value (likely well under 3600) for up to an hour and then disappears. Since an absent series makes the expression yield nothing, and `for: 15m` needs 15 minutes of continuous truth, `KustoLogsDataStale` never fires for the exact condition it was written to detect.

Two aggravators: `GatherLogs` errors only `c.errorCounter.Inc()` + `logger.Error` + `continue` (~141–144), leaving stale entries in place; and `ConcurrentQueries` uses `errgroup.WithContext`, so the first failing query cancels the shared `queryCtx` and aborts its siblings, wiping out a whole cluster's cycle on one bad table.

## What would need to change (not applied)

Give each of the five service-log queries a distinct name — either add `children:` entries to `infraServiceLogs` in `queries.yaml`, or have `serviceLogs` build a per-table name rather than reusing `def.Name`; reconcile the case of `systemdLogs`/`systemdlogs` between the exporter and both rule copies; replace the unconditional `foundLogSources[key] = ...` with a max-timestamp comparison; recompute age at scrape time in `Collect` (or store the timestamp rather than a pre-baked metric) so the value ages upward; and align `cacheTTL`, `collectionInterval` and `KustoQueryInterval` so a series cannot outlive its refresh cadence. A test asserting the rule's matchers against label values actually emitted by the collector would keep the two ends married.

I made no edits; this was a read-only investigation.