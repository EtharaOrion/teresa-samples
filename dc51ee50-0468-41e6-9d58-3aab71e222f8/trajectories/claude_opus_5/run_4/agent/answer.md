I have traced the full dependency chain end to end and verified each link in the real source. Here is my analysis.

# `KustoLogsDataStale` — full dependency chain, and why the two ends don't actually meet

Read-only investigation; nothing in the repo was modified.

## The chain, file by file

**1. The query text** — `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`, mirrored into `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`:

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
```
`for: 15m`. Annotations interpolate `$labels.cluster`, `$labels.table`, `$labels.kusto_cluster`.

**2. The series** — `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-41` declares `kusto_logs_age_in_seconds` with label order `{kusto_cluster, cluster, table}`; lines 150-157 fill them positionally with `c.kustoCluster, clusterName, logSource`.

**3. Where the value comes from** — line 153: `float64(time.Since(foundLogSources[logSource]).Seconds())`, i.e. wall-clock age of the newest observed row timestamp.

**4. Where `table` comes from** — this is the load-bearing link. `logSource` is a key of `foundLogSources`, and line 120 sets `key := logLine.QueryName`. Tracing backwards: `NormalizedLogLine.QueryName` is assigned in `mustgather/gather.go:650` from `tagged.QueryName`; `TaggedRow` is constructed in `kusto/client.go:154` as `QueryName: query.GetName()`; `GetName()` returns `templateQuery.name`; that is set in `kusto/query.go:246-269` (`buildQuery`) from the `name` argument, which `Build` (`query.go:296-312`) passes as `child.Name` when the definition has children, else `def.Name`.

So **the `table` label is literally the `name:` field of an entry in `tooling/hcpctl/pkg/kusto/templates/builtin/queries.yaml`** — not a Kusto table name.

**5. Which names are reachable from the exporter.** The exporter sets `GatherInfraLogs: true` (line 130), which `NewGatherer` copies to `infraLogsOnly` (`gather.go:239`), so `GatherLogs` short-circuits at line 333 into `gatherInfraLogs`. That function builds exactly three definitions: `kubernetesEvents`, `systemdLogs`, and `infraServiceLogs` (via `serviceLogs(queryFactory, "infraServiceLogs", ...)`). None of the three has `children:` in `queries.yaml`, so `Build` takes the `def.Name` branch.

## Where the two ends are genuinely married up

Only `kusto_cluster` and `cluster` line up cleanly. `cluster` is the `--cluster-names` flag, sourced from `deploy/values.yaml` as `{{ .svc.aks.name }},{{ .mgmt.aks.name }}`, which `config/config.yaml:524` and `:657` render as `<env>-<region>-svc-1` and `<env>-<region>-mgmt-<stamp>`. Those genuinely match the alert's `.*-svc-.*` regex, and the regex correctly separates svc (7200s) from mgmt (3600s). That half of the rule is sound. The same `clusterName` is also injected into every KQL template as `| where cluster == '{{.ClusterName}}'`, so the label and the query filter are the same string — that binding is real.

## What makes the disagreement silent

**The `table` matcher can never match.** The emitted values are `kubernetesEvents`, `systemdLogs`, `infraServiceLogs` (camelCase). The alert matches `table="systemdlogs"` (lowercase). PromQL label matching is exact and case-sensitive, and I found no `metricRelabelings` in `deploy/templates/servicemonitor.yaml` to normalize it. Consequences:

- The third disjunct, `table="systemdlogs" and cluster=~".*-svc-.*"` → `> 7200`, selects the empty set. The deliberate 2-hour allowance for svc systemd logs is dead code.
- The real `systemdLogs` series instead falls through `table!="systemdlogs"` (true, since `"systemdLogs" != "systemdlogs"`) and is judged at 3600s. So svc systemd logs alert at the mgmt threshold — the exact case the rule was written to exempt.

This is silent because the rule still *fires* and looks healthy; nothing errors, no series is missing, and the `!=` matcher happily selects the very series the other clauses meant to carve out. There is no test that would catch it either: `kusto-logs-age-prometheusRule_test.yaml` hand-writes its fixtures (`table="ContainerLog"`, `table="systemdlogs"`) rather than deriving them from the exporter. `ContainerLog` is not a value this code can emit at all, and `systemdlogs` is the lowercase spelling. The fixtures agree with the rule and both disagree with reality, so the suite passes green while validating a label vocabulary that does not exist.

**A second, independent collision:** `serviceLogs` (`mustgather/queries.go:43-57`) loops over the five `ServicesTables` (`containerLogs`, `clustersServiceLogs`, `fleetLogs`, `frontendLogs`, `backendLogs`), but `WithTable(table)` only substitutes `{{.Table}}` into the KQL body — the query *name* stays `infraServiceLogs` for all five. All five collapse onto one cache key. Worse, `kusto_logs_current.go:121` is first-write-wins (`if _, ok := foundLogSources[key]; !ok`), and these run concurrently through `ConcurrentQueries`' errgroup, so which of the five tables supplies the timestamp is nondeterministic. One totally dead table is masked by any other live table, and the annotation `"table {{ $labels.table }}"` will name `infraServiceLogs`, which points an on-call engineer at no particular ingestion pipeline.

Note also `queryOptions.OrderBy = kusto.OrderByDesc` with `Limit = 100`, so rows arrive newest-first and the first-write-wins guard does pick the newest row — the guard is load-bearing, not incidental. If the ordering were ever flipped to the `NewQueryOptions` default of `OrderByAsc`, the metric would silently report the age of the *oldest* row in the window instead.

## Why a stale value survives for a period after rows stop arriving

The gauge does not climb when ingestion stops; it freezes at its last value and then vanishes. Three mechanics compound:

1. **`foundLogSources` is rebuilt per collection** (line 114) and the publish loop at line 147 is `for logSource := range foundLogSources`. If a query returns zero rows, that key is absent, so `cache.Set` is never called for it. There is no path that writes a "no data" observation.
2. **The cache is write-only-on-success with a TTL.** `metricscache/cache.go:52-56` stamps `created: time.Now()` on `Set`; `GetAll` (58-71) drops an entry only once `now.Sub(e.created) >= ttl` and otherwise returns the stored metric verbatim. So on failure the *previous* metric object keeps being served — with its frozen value, computed against a `time.Since` that was evaluated at the earlier collection. `deploy/values.yaml` sets `cacheTTL: "60m"`.
3. **Failures skip the whole cluster.** Line 141-145: if `GatherLogs` errors, it bumps the error counter and `continue`s, leaving every prior entry for that cluster intact until TTL.

Net effect: for up to **60 minutes** after ingestion stops, `kusto_logs_age_in_seconds` reports a stale, constant, under-stated value. The alert threshold is 3600s and the freeze window is 3600s, so a series frozen at a healthy value can hide a genuine outage for the entire TTL, then disappear rather than crossing the threshold. `for: 15m` cannot help: it requires 15 minutes of *continuously breaching samples*, and a vanished series resets the pending state. The lookback window is also capped — `TimestampMin = time.Now().Add(-120 * time.Minute)` (line 108) — so any gap older than 120 minutes yields no rows at all and can only ever produce absence, never a value above 7200. **The `> 7200` comparison is doubly unreachable: once by the label-case mismatch, and again because the query window structurally caps observable age at 7200 seconds.**

Detection therefore depends entirely on `absent()`/`up`-style monitoring, and I found no such companion rule for this metric.

Separately, `collectLoop` (`serve.go:130-150`) runs at `collectionInterval` (`2m` in values.yaml) but `CollectMetricValues` self-throttles via `lastRun` against `KustoQueryInterval = 5m` (line 97), so most invocations return immediately. The effective refresh is 5 minutes, not 2 — worth knowing when reasoning about how promptly a frozen value can recover.

## What would need to change (not applied)

- Reconcile the `table` vocabulary at one end: either lowercase/normalize `QueryName` where the label is set in `kusto_logs_current.go`, add `metricRelabelings` in the ServiceMonitor, or change the matchers to the camelCase names — and update *both* the YAML rule and the generated Bicep, since they are duplicated.
- Give the five service tables distinct label values by threading the table name through into the query name rather than only into the template body.
- Emit an explicit stale/absent signal (or a last-success timestamp) so that "no rows" is representable, instead of relying on cache expiry.
- Derive the rule-test fixtures from the exporter's actual label output so this class of mismatch fails the suite.