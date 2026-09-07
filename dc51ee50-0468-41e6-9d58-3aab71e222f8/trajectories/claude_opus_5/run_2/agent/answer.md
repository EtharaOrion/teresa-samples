I've traced the complete chain. Here is my analysis.

# `kusto_logs_age_in_seconds`: query text → labels → published series

Read-only investigation. Nothing in the repo was modified.

## The two ends

**Consumer (query text)** — `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`, generated into the deployed `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`:

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
for: 15m
```

**Producer (series)** — `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-42`:

```go
KustoLogsAgeInSecondsDesc = prometheus.NewDesc(
    "kusto_logs_age_in_seconds",
    "Age of last log in seconds from Kusto",
    []string{"kusto_cluster", "cluster", "table"},
    nil,
)
```

Emitted at `kusto_logs_current.go:150-157` with positional args `c.kustoCluster, clusterName, logSource`. So `table` == `logSource`.

## Dependency chain for the `table` label

`logSource` is a key of `foundLogSources`, and the key is set at line 119: `key := logLine.QueryName`. Following `QueryName` backwards:

1. `kusto_logs_current.go:119` — `key := logLine.QueryName`
2. `mustgather/gather.go:650` — `normalizedLogLine.QueryName = tagged.QueryName`
3. `kusto/client.go:154` — `TaggedRow{Row: row, QueryName: query.GetName(), QueryType: query.GetQueryType()}`
4. `kusto/query.go:81-83` — `GetName()` returns `templateQuery.name`
5. `kusto/query.go:296-312` — `Build()` sets `name` from `child.Name` when `def.Children` is non-empty, else from `def.Name`
6. `templates/builtin/queries.yaml` — **no definition has a `children:` key** (verified: `grep -n "children"` returns nothing), so the name is always `def.Name`.

The collector runs `GatherInfraLogs: true` (`kusto_logs_current.go:130`), so `GatherLogs` dispatches straight to `gatherInfraLogs` (`gather.go:329-331`). That function issues exactly three definitions (`gather.go:533, 545, 557`): `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.

**Therefore the only three values `table` can ever take are `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.** The label is a *query-definition name*, not a Kusto table name.

## Where the ends are genuinely married up

Only in the string identity between YAML `def.Name` and the PromQL matcher literal. There is no shared constant, no enum, no generation step, and no validation joining `templates/builtin/queries.yaml` to the alert expression. Two YAML files in different trees, coupled purely by hand-typed text.

## What makes the disagreement silent

**1. Case mismatch on the only literal matcher.** The producer emits `systemdLogs` (capital L, `queries.yaml:5`). The alert matches `systemdlogs` (all lowercase). Prometheus label matching is byte-exact and there is no case normalization anywhere on the path — I checked: `grep -rn "ToLower\|ToUpper"` across the exporter, `pkg/kusto`, `pkg/mustgather` and `metricscache` returns nothing.

Consequence: the `table="systemdlogs"` arms select nothing, and `systemdLogs` instead falls through the `table!="systemdlogs"` arm. Functionally the SVC-specific 7200s carve-out is dead — systemd logs on `*-svc-*` clusters are held to 3600s instead of the intended 7200s. This is silent because a non-matching label selector is not an error in PromQL; it is simply an empty vector, and `or` with an empty vector is a no-op.

**2. Five real tables collapse into one series.** `gather.go:557` calls `serviceLogs(queryFactory, "infraServiceLogs", ...)`, which at `mustgather/queries.go:49-55` loops over `ServicesTables` = `containerLogs`, `clustersServiceLogs`, `fleetLogs`, `frontendLogs`, `backendLogs`, building five queries via `kusto.WithTable(table)`. The table only reaches the KQL body (`{{.Table}}` in `infra/service_logs.kql.gotmpl`); it never reaches `def.Name`. All five come back tagged `QueryName == "infraServiceLogs"`.

The aggregation at `kusto_logs_current.go:119-123` is first-write-wins:
```go
if _, ok := foundLogSources[key]; !ok {
    foundLogSources[key] = logLine.Timestamp
}
```
and the five queries run concurrently (`gather.go:604-607`, `ConcurrentQueries`), so the surviving timestamp is whichever query's first row lands first — nondeterministic.

This is the more serious silent failure: if one of the five stops ingesting it returns zero rows, but the other four keep the shared `infraServiceLogs` key freshly populated, so the alert can never fire for the dead table. Four-fifths of service-log ingestion is effectively unmonitorable through this rule.

**3. The unit test validates a value that cannot exist.** `observability/alerts/kusto-logs-age-prometheusRule_test.yaml` feeds `table="ContainerLog"` — not in the producible set (`containerLogs` is a *KQL* table, and it never becomes a label anyway). The test therefore exercises only the `table!="systemdlogs"` arm, which passes for any string, so promtool (`tooling/prometheus-rules/internal/generator.go:325`, wired via `observability/alerts-sl-services.yaml:16`) confirms nothing about the real label vocabulary. `promtool test rules` checks a rule against hand-written `input_series`; it has no knowledge of the exporter, so it cannot catch a producer/consumer vocabulary drift. That is the mechanism by which all of the above passes CI green.

## Why a stale value survives after rows stop arriving

The series is served from a TTL cache, not computed at scrape time.

- `Collect` (`kusto_logs_current.go:88-92`) only replays `c.cache.GetAll()`; it performs no query.
- The value is frozen at `Set` time by `prometheus.MustNewConstMetric(..., float64(time.Since(foundLogSources[logSource]).Seconds()), ...)` (`:150-153`). It is a fixed float, **not** a function of scrape time.
- Eviction is lazy and only in `GetAll` (`tooling/metricscache/cache.go:59-71`): `if now.Sub(e.created) >= c.ttl { delete } else { append }`.

With `cacheTTL: "60m"` (`tooling/aro-hcp-exporter/deploy/values.yaml`), when ingestion dies:

- **First ~60 minutes** — the last successfully computed age is re-served verbatim on every scrape. If it was healthy (say 200s) at the moment ingestion stopped, it stays exactly 200s. It never grows, so `> 3600` never becomes true.
- **After 60 minutes** — the entry is evicted and the series disappears. The expression has no `absent()` arm, so an absent series is also not an alert.

The failure is therefore invisible both before and after eviction. Two additional amplifiers:

- **Error path preserves staleness.** On query failure `kusto_logs_current.go:141-145` increments `errorCounter`, logs, and `continue`s — the cache is left untouched, so the stale metric keeps being served.
- **Refresh is coarser than it looks.** `collectionInterval` is `2m` (values.yaml) but `CollectMetricValues` self-gates on `KustoQueryInterval = 5 * time.Minute` (`:33-34`, `:97-100`), so real refresh lands every 6 minutes and intervening ticks are no-ops. Combined with a 120-minute query window (`TimestampMin = now-120m`, `:107`), the reported age is coarse — but that only widens the detection floor; it is not what causes the freeze.

## What would need to change (not applied)

1. Make `table` carry the real table. Propagate `TemplateData.Table` (or the loop variable in `mustgather/queries.go:49`) into `templateQuery.name`, or add a distinct field on `TaggedRow`/`NormalizedLogLine`, so the five `ServicesTables` produce five distinct series instead of one.
2. Fix the case: either rename `systemdLogs` → `systemdlogs` in `queries.yaml` (risky, it is also a query lookup key at `gather.go:545`), or correct the two matcher literals in the alert to `systemdLogs`. Changing the alert is the lower-blast-radius option, and the generated `.bicep` must be regenerated to match.
3. Correct `ContainerLog` in the test file to a producible value, and add a `for`-window case that exercises the `systemdLogs` SVC arm so the case bug becomes catchable.
4. For staleness, either recompute age at scrape time from a stored timestamp instead of caching a frozen float, or set `cacheTTL` below the alert threshold and add an `absent()`/`up`-style arm so a vanished series alerts.

I recommend confirming (1) and (2) against whoever owns `observability/` before any change, since renaming `systemdLogs` has a second consumer at `gather.go:545`.