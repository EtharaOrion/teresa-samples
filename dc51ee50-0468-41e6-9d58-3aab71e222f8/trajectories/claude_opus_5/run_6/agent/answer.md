I have all the pieces now, ready to put together the final response.

I traced the full chain, source-first, and changed nothing. Below is the real dependency path from the alert's query text to the labels and value on the published series, where the two ends genuinely meet, where they silently disagree, and why a stale value survives after rows stop arriving.

## The two ends

**Consumer** — `observability/alerts/kusto-logs-age-prometheusRule.yaml:13` (alert `KustoLogsDataStale`, `for: 15m`):

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
```

**Producer** — `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-43`:

```go
KustoLogsAgeInSecondsDesc = prometheus.NewDesc(
    "kusto_logs_age_in_seconds",
    "Age of last log in seconds from Kusto",
    []string{"kusto_cluster", "cluster", "table"}, nil)
```

## The `table` label chain, traced through every file

The series is constructed at `kusto_logs_current.go:149-157`; the third label argument is `logSource`, the key ranged over from `foundLogSources` (line 147). That map is keyed at line 119 by **`logLine.QueryName`** — not by any table name. Following `QueryName` backwards:

1. `mustgather/gather.go:651` — `normalizedLogLine.QueryName = tagged.QueryName`
2. `kusto/client.go:154` — `outputChannel <- TaggedRow{Row: row, QueryName: query.GetName(), ...}`
3. `kusto/query.go:263-268` — `buildQuery` returns `&templateQuery{name: name, ...}`, and `GetName()` returns that field
4. `kusto/query.go:301-315` — `Build` passes `child.Name` when `def.Children` is non-empty, otherwise `def.Name`
5. `templates/builtin/queries.yaml` — supplies `def.Name`

The exporter sets `GatherInfraLogs: true` (`kusto_logs_current.go:130`), so `gather.go:333` short-circuits into `gatherInfraLogs`, which issues exactly three definitions: `kubernetesEvents` (line 537), `systemdLogs` (line 549), and `infraServiceLogs` via `serviceLogs(...)` (line 557). I parsed `queries.yaml` with a YAML loader: **none of these three has a `children:` key**, so step 4 always takes the `def.Name` branch. The only `table` label values the exporter can ever emit are therefore:

```
kubernetesEvents    systemdLogs    infraServiceLogs
```

Note the fourth arm of the funnel: `serviceLogs` (`mustgather/queries.go:43-57`) loops over `ServicesTables` = `containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs` and injects each via `kusto.WithTable(table)`. That value lands in the KQL template body (`{{.Table}}` in `infra/service_logs.kql.gotmpl`) — it is *never* propagated to the query name. So five distinct table queries all run concurrently (`queryclient.go:62-83`) and all tag their rows with the single name `infraServiceLogs`, collapsing into one map key. The real table identity is discarded before it can reach a label.

## Where the two ends are genuinely married up

Only `cluster`. The deployment passes `--cluster-names={{ .svc.aks.name }},{{ .mgmt.aks.name }}` (`deploy/values.yaml`, `deploy/templates/deployment.yaml:36-40`); resolving `config/rendered/dev/dev/westus3.yaml` gives `dev-westus3-svc-1` and `dev-westus3-mgmt-1`. That same string flows into `queryOptions.InfraClusterName` (line 107) → `WithClusterName` → `where cluster == '{{.ClusterName}}'` in the KQL, and is also emitted verbatim as the `cluster` label (line 155). So the alert's `cluster=~".*-svc-.*"` / `cluster!~".*-svc-.*"` discrimination does work as intended. `kusto_cluster` is likewise consistent — it is the `--kusto-cluster` flag, used both to build the endpoint and as the label.

## What makes the disagreement silent

The alert matches `table="systemdlogs"`; the exporter emits `systemdLogs`. Prometheus label matching is exact and case-sensitive, so **arms 2 and 3 of the expression can never select a sample**. They are not errors — they are simply empty vector selectors, which is why nothing surfaces.

The failure is worse than dead arms, because arm 1 is `table!="systemdlogs"`, and `systemdLogs` *satisfies* that inequality. Every systemd series is swept up by arm 1 and evaluated against the 3600s threshold. The intended 7200s exemption for svc clusters is therefore not merely inert — it is actively bypassed, and svc systemd data alerts an hour earlier than designed. A negative matcher is what converts a typo into a wrong-threshold bug instead of a no-op.

Nothing catches this because the unit test at `observability/alerts/kusto-logs-age-prometheusRule_test.yaml` writes its own `input_series` by hand, using `table="ContainerLog"` and `table="systemdlogs"`. Neither string is producible by the exporter (`ContainerLog` is not even one of the five `ServicesTables` spellings — that list has `containerLogs`). The fixtures assert the rule against a vocabulary that no producer emits, so the tests pass while the deployed rule matches nothing. There is no shared constant, schema, or generation step tying `queries.yaml` names to the alert selectors; the coupling is by convention only, and no test crosses the boundary. I also confirmed there are no Go tests anywhere under `tooling/aro-hcp-exporter/`.

## Why a stale value survives for a period once rows stop arriving

Three mechanisms compose:

1. **The value is frozen at write time, not at scrape time.** Line 153 computes `float64(time.Since(foundLogSources[logSource]).Seconds())` and bakes the result into a `prometheus.MustNewConstMetric`. `Collect` (line ~90) merely replays `c.cache.GetAll()`. Scrapes never re-derive the age, so the reported number does not advance with wall-clock time — it is a snapshot of the age as of the last successful collection.

2. **"No rows" produces no write at all.** The publish loop is `for logSource := range foundLogSources`. `foundLogSources` is a fresh map per cluster per run (line 114), populated only from rows that actually arrive (lines 118-125). If a source returns zero rows inside the 120-minute window (`TimestampMin = now-120m`, line 108), it never becomes a key, the loop body never executes for it, and `cache.Set` is never called. The absence of data is indistinguishable from the absence of an update. Identically, a query error hits `c.errorCounter.Inc()` then `continue` (lines 142-144), skipping the entire publish block for that cluster.

3. **The cache serves the last good entry until TTL.** `metricscache/cache.go:59-71` only evicts inside `GetAll`, when `now.Sub(e.created) >= c.ttl`. With `cacheTTL: "60m"` (`deploy/values.yaml`), a series whose ingestion has stopped keeps being exported with its last-known-good, non-increasing value for up to **60 minutes**, then vanishes outright rather than crossing any threshold.

The net effect: the metric's staleness signal is suppressed for the TTL window and then disappears, so the very condition the alert exists to detect is the condition under which the alert's input goes quiet. This is compounded by pacing — `collectionInterval: "2m"` drives `collectLoop` (`serve.go:130-150`), but `CollectMetricValues` self-throttles at line 97 against a hardcoded `KustoQueryInterval = 5 * time.Minute`, so ~3 of every 5 wakeups return immediately.

Relatedly, `--kusto-query-interval` is plumbed through `RawOptions`/`ValidatedOptions` (`options.go:48, 64, 120, 160`) but is dropped at the `Complete` boundary: `CompletedOptions` has no such field, and `NewKustoLogsCurrentCollector` never receives it. Line 97 reads the package constant instead, so the flag is inert.

One further latent issue in the same path: line 121 uses `if _, ok := foundLogSources[key]; !ok` — first-write-wins. With `OrderBy = kusto.OrderByDesc` and a single query that would yield the newest row, but the five `infraServiceLogs` queries run concurrently through `errgroup` and interleave into one channel under one shared key, so the winner is a race between five independently-ordered result streams. The recorded timestamp is the first row observed from whichever query wins, not the maximum across them, which can overstate the age.

## What would need to change (not applied)

- Give the emitted `table` label real table identity: either add `children:` entries to `infraServiceLogs` in `queries.yaml` so `Build` names each child, or carry the `WithTable` value through `TaggedRow`/`NormalizedLogLine` into the label at `kusto_logs_current.go:149`. Then align the alert selectors and the test fixtures to that vocabulary.
- Fix the case mismatch in the alert. Because arm 1 is a negative matcher, correcting only the producer or only the alert in isolation still leaves the thresholds wrong; both ends must move together.
- For the frozen value, either store the raw timestamp and compute the age inside `Collect`, or use a proper `absent()`/`up`-based staleness arm so a disappearing series alerts instead of going silent.
- Use `max` rather than first-write-wins at line 121.

These are descriptions only — the working tree is untouched and my diff is empty.