I've traced the full chain. Here is my analysis.

## The dependency chain, end to end

**1. The query text** — `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`, mirrored into the generated Azure copy at `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`:

```
kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600
  or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200
```
with `for: 15m`. The rule file is pulled into the bundle by `observability/alerts-sl-services.yaml:16`.

**2. The series contract** — `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-43` declares the name and label set `{kusto_cluster, cluster, table}`. This `Desc` is the only place the three label *names* are fixed; nothing validates the label *values*.

**3. The publish site** — `kusto_logs_current.go:150-157` builds the const metric. Label values in positional order: `c.kustoCluster` (from `--kusto-cluster`), `clusterName` (loop over `c.clusterNames`, from `--cluster-names`, populated in `deploy/values.yaml:26` as `{{ .svc.aks.name }},{{ .mgmt.aks.name }}`), and `logSource`.

**4. What `logSource` actually is** — it is a map key of `foundLogSources`, set at `kusto_logs_current.go:119` to `logLine.QueryName`. That is stamped in `mustgather/gather.go:650` from `tagged.QueryName`, which `kusto/client.go:154` sets to `query.GetName()`, which `kusto/query.go:312` takes from `def.Name` in `templates/builtin/queries.yaml`.

**5. Which names can reach the label** — the exporter sets `GatherInfraLogs: true` (`kusto_logs_current.go:130`), which becomes `infraLogsOnly` (`gather.go:239`), so `GatherLogs` short-circuits to `gatherInfraLogs` (`gather.go:331-333`). That function uses exactly three definitions: `kubernetesEvents` (`gather.go:533`), `systemdLogs` (`gather.go:545`), and `infraServiceLogs` (`gather.go:557`).

## Where the two ends are genuinely married up

Only `kusto_cluster` and `cluster` are. The `table` label is where the marriage breaks.

**The casing mismatch.** The exporter can only ever emit `table="systemdLogs"` (capital L, from `queries.yaml:5`). The alert matches `table="systemdlogs"`, all lowercase, in all three branches. PromQL label matching is byte-exact and there is no `ToLower` anywhere on this path — I grepped the exporter, `pkg/kusto` and `pkg/mustgather` and found none. The only `lower` in the deployment is `--kusto-region` (`deployment.yaml:39`), which is a different field.

The consequence is not that the rule silently does nothing. It is worse and asymmetric: branch 1 is `table!="systemdlogs"`, and since no series ever carries that value, **every** series matches branch 1. So systemd logs on service clusters are silently held to the 3600s threshold via branch 1 rather than the intended 7200s, while branches 2 and 3 are dead code. The deliberate service-cluster exemption never takes effect.

**Why the disagreement is silent.** Three reinforcing reasons. The `Desc` at line 38-43 pins label *names* only, so the registry cannot object to a value. The alert is a threshold comparison with no `absent()` guard — I checked `observability/alerts/` and `absent` appears only in the upstream Kubernetes rules, never here — so a label set that matches nothing produces an empty vector, which is indistinguishable from "everything healthy." And the unit test at `observability/alerts/kusto-logs-age-prometheusRule_test.yaml` invents its own input series with `table="ContainerLog"` and `table="systemdlogs"` (lines 8, 38, 68, 89). Neither value is producible by the exporter: `ContainerLog` does not appear in `queries.yaml` at all, and `systemdlogs` is the wrong case. The fixture asserts the rule against synthetic data, so it passes green while the production label set never matches.

**A second, independent collapse in the same label.** `mustgather/queries.go:43-53` loops over `ServicesTables` — `containerLogs`, `clustersServiceLogs`, `fleetLogs`, `frontendLogs`, `backendLogs` (`queries.go:21-27`) — and builds five distinct queries from the single `infraServiceLogs` definition, varying only the injected `{{.Table}}` via `WithTable`. `Build` at `query.go:312` names every one of them `def.Name`, so all five return `QueryName == "infraServiceLogs"`. All five run concurrently into one unbuffered channel (`queryclient.go:65-68`), and `kusto_logs_current.go:121-123` is first-arrival-wins:

```go
if _, ok := foundLogSources[key]; !ok {
        foundLogSources[key] = logLine.Timestamp
}
```

So five independent ingestion streams collapse into one `table="infraServiceLogs"` series whose value is decided by a scheduling race. `queryOptions.OrderBy = kusto.OrderByDesc` (line 112) correctly makes the first row within any one query the newest, but across the five it is arbitrary. If `containerLogs` is healthy and `backendLogs` has been dead for a day, the series can report a few seconds of age and the four dead tables have no way to influence it. The `table` dimension the alert annotation promises to name ("Kusto log data for table {{ $labels.table }}") cannot identify which table is actually broken.

## Why a stale value survives after rows stop

`Collect` (`kusto_logs_current.go:88-92`) serves purely from cache; the scrape never touches Kusto. Refresh is gated to at most once per `KustoQueryInterval` = 5 minutes (`line 34`, `lines 97-99`), against a 30s ServiceMonitor scrape (`servicemonitor.yaml:8`) and a 1m collection loop (`serve.go:130-150`).

The publish loop is:

```go
for logSource := range foundLogSources {
        ...
        c.cache.Set(key, ...)   // lines 147-158
}
```

It iterates over sources that were **found**, not over sources that were **expected**. When a table stops producing rows, its key never enters `foundLogSources`, so `Set` is never called for it. There is no delete-on-absence and no zero-fill. The previous `cacheEntry` survives untouched — crucially including its `created` stamp, which `cache.go:55` only refreshes on `Set`. Eviction in `GetAll` (`cache.go:59-71`) triggers on `now.Sub(e.created) >= c.ttl`, so the clock is measured from last *successful write*, not from last scrape or last attempt. With `cacheTTL: "60m"` (`deploy/values.yaml:23`), a dead series keeps being exported **frozen at its last-known value** for up to 60 minutes, then disappears entirely.

The same freeze happens on the error path: `gatherer.GatherLogs` failing hits `continue` at `kusto_logs_current.go:144`, incrementing a counter and skipping the publish loop, leaving the whole cluster's entries stale.

**The net behavioural consequence:** the gauge does not climb when ingestion breaks — it freezes, then vanishes. If the last good reading was, say, 300 seconds, it stays 300 for an hour and never crosses 3600, so `for: 15m` never arms. Then the series goes absent, and with no `absent()` guard the rule still cannot fire. `KustoLogsDataStale` is structurally incapable of detecting a full ingestion stop; it can only catch a stream that is still delivering rows but lagging by more than an hour, and even then only if the winner of the five-way race happens to be the lagging one.

One loose end worth flagging: `--kusto-query-interval` is defined and validated (`options.go:160`, `options.go:120`) but `CompletedOptions` (`options.go:82-90`) drops the field, and `NewKustoLogsCurrentCollector` (`options.go:200`) is never passed it. The collector uses the hardcoded package constant instead, so that flag is silently inert.

## What would need to change (not applied)

Reconciling the casing between `queries.yaml` and both rule copies is necessary but not sufficient — the `infraServiceLogs` name collapse means the `table` label still would not distinguish the five service tables, so a per-table name (or threading `WithTable`'s value onto `TaggedRow`) is needed for the label to carry the meaning the alert assumes. Separately, the publish loop would need to iterate the expected source set rather than the found set so absence produces a rising or zeroed value instead of a frozen one, and the test fixture would need to use label values the exporter can actually emit so the mismatch is caught mechanically. I have made none of these changes; this was a read-only investigation and the working tree is untouched.

All claims are now verified against source. Sending the corrected analysis.

# `kusto_logs_age_in_seconds`: query text → labels → value

**First, a correction to my own earlier messages.** I twice asserted that the gauge "freezes and never crosses 3600, so the alert is incapable of firing." That is **wrong**, and my own simulation disproved it. `TimestampMin` is a *rolling* `now-120m` window (`kusto_logs_current.go:108`), so on each refresh the same newest row yields a *larger* age. The value climbs 0 → 7200s and does cross 3600. The real defects are different, and narrower. Below is what the source actually supports.

## The chain, end to end

1. **Query** — `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`, mirrored to Azure at `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep:2223`, `for: 15m`. Rule file is pulled in via `observability/alerts-sl-services.yaml:16`.
2. **Series contract** — `tooling/aro-hcp-exporter/internal/metrics/kusto_logs_current.go:38-43` declares the name and label set `{kusto_cluster, cluster, table}`. This is the only place the label *names* are fixed; nothing validates the *values*.
3. **Publish site** — `kusto_logs_current.go:150-157`. `kusto_cluster` ← `--kusto-cluster`; `cluster` ← loop over `--cluster-names` (`deploy/values.yaml:26` = `{{ .svc.aks.name }},{{ .mgmt.aks.name }}`); `table` ← `logSource`.
4. **`table` is not a table name** — it is a *query definition name*: `kusto_logs_current.go:119` takes `logLine.QueryName`, set at `mustgather/gather.go:650` from `TaggedRow.QueryName` (`kusto/client.go:154`), which is `def.Name` from `templates/builtin/queries.yaml` (`kusto/query.go:312`).
5. **Reachable names** — `GatherInfraLogs: true` (`:130`) → `infraLogsOnly` (`gather.go:239`) → `gatherInfraLogs` (`gather.go:331-333`), which issues exactly three definitions: `kubernetesEvents` (`:533`), `systemdLogs` (`:545`), `infraServiceLogs` (`:557`).

So the only `table` values that can ever exist are **`kubernetesEvents`, `systemdLogs`, `infraServiceLogs`**.

## Where the two ends are genuinely married up

Only on `kusto_cluster` and `cluster`, and only on the *first* disjunct. `table!="systemdlogs"` is true for all three emitted names, so every real series is evaluated at the 3600s threshold. That part works.

## What makes a disagreement silent

**(a) The `systemdlogs` carve-out is dead code.** The exporter emits `systemdLogs`; the rule matches `systemdlogs`. Prometheus label matching is case-sensitive, so disjuncts 2 and 3 select nothing, and systemd logs are silently swept into the generic 3600s branch — losing the intended 7200s tolerance for `-svc-` clusters. A mismatched matcher yields an empty vector, which is indistinguishable from "healthy": there is no `absent()` guard here, unlike the upstream rules at `observability/alerts/kubernetesControlPlane-prometheusRule.upstream.yaml:587`.

**(b) The third disjunct is unreachable even if the case were fixed.** The value is capped by the 120-minute lookback, so age ∈ [0, 7200]. `> 7200` can never be satisfied. I verified this arithmetically.

**(c) The unit test cannot catch (a) or (b).** `kusto-logs-age-prometheusRule_test.yaml` invents its own `input_series` with `table="ContainerLog"` (lines 8, 29, 89) and `table="systemdlogs"` (38, 68). Neither value is producible: `ContainerLog` appears nowhere in `queries.yaml`, and `systemdlogs` is the wrong case. The fixture tests the rule against a fictional exporter, so it stays green while production matches nothing.

**(d) Five tables collapse into one series.** `mustgather/queries.go:43-53` builds five queries from the single `infraServiceLogs` definition (`containerLogs`, `clustersServiceLogs`, `fleetLogs`, `frontendLogs`, `backendLogs`) via `WithTable`, but all five carry the same `QueryName`. They run concurrently into one unbuffered channel (`queryclient.go:65-68`), and `kusto_logs_current.go:121-123` is first-arrival-wins (`if _, ok := ...; !ok`). With `OrderByDesc` (`:112`) the first row per query is that query's newest, so the surviving value is whichever query won the race — not the worst. One healthy table masks four dead ones, and `table` cannot say which broke.

## Why a stale value survives, and for how long

The publish loop at `:147` iterates over sources that were **found**, never over sources that were **expected**. When a table stops producing, its key never enters `foundLogSources`, so `Set` is never called — there is no delete-on-absence and no zero-fill. The prior `cacheEntry` survives with its original `created` stamp, which `cache.go:55` refreshes only on `Set`. Eviction in `GetAll` (`cache.go:65`) keys off `now.Sub(e.created) >= c.ttl` — time since the last *successful write*, not since the last scrape.

Concretely, with `cacheTTL: "60m"` (`values.yaml:23`) and the 120m window, tracing the value after rows stop at t=0:

- t=0→120m: the newest row is still inside the rolling window, so the age climbs 0→7200s. It crosses 3600 at ~t=60m and, after `for: 15m`, **fires at ~t=75m**.
- t=125m: the row falls out of the window, `Set` stops being called, and the value **freezes at 7200**.
- t=~180m: TTL expires from the last successful `Set`, the entry is evicted, the series **disappears**, and the firing alert **silently self-resolves while the outage is still ongoing**.

The same freeze happens on query failure: `gatherer.GatherLogs` errors bump a counter and `continue` (`:141-145`), leaving that cluster's entries stale rather than stale-marked. `KustoQueryInterval` = 5m (`:34`, gated at `:97-99`) is independent of both the 30s scrape (`servicemonitor.yaml:8`) and the 1m collection loop, so scrapes mostly re-serve cached values.

Note also that `--kusto-query-interval` is parsed and carried into `ValidatedOptions` (`options.go:120`) but is dropped at `Complete` — `CompletedOptions` (`options.go:82-90`) has no such field and `NewKustoLogsCurrentCollector` (`options.go:200`) is never passed it. The flag is inert; the hard-coded 5m constant always wins.

## What would need to change (not applied)

Align the case between `queries.yaml` and both rule copies; widen the lookback past 7200s or lower the third threshold so it is reachable; give `infraServiceLogs` a per-table label so the five streams stop colliding; rewrite the publish loop to emit for every *expected* source so absence produces a rising or zeroed value rather than a frozen one; and rebuild the test fixture from label values the exporter can actually emit, so the mismatch is caught mechanically.

The working tree is unmodified; this was read-only inspection.