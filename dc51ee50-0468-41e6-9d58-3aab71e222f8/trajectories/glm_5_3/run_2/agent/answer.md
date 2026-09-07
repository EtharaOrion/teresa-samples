The user keeps asking me to continue. I should finish my report. My previous message got cut off. Let me send the final complete answer via the finish tool now, being comprehensive but complete in one message.

READ-ONLY INVESTIGATION COMPLETE — no files were created, edited, or deleted; only `grep`/`sed`/`cat`/`find` were used.

# The real dependency chain: query text → labels → value → published series (`kusto_logs_age_in_seconds`)

## 0. Runtime loop — how the series is published at all
- `tooling/aro-hcp-exporter/internal/cmd/serve.go:131-148` — `collectLoop` calls `collector.CollectMetricValues(ctx)` every `collectionInterval`, then sleeps. Code default is 1m (`options.go:36`), but the chart overrides it: `deploy/values.yaml → collectionInterval: "2m"`, passed as `--collection-interval` in `deploy/templates/deployment.yaml`.
- `serve.go` starts promhttp on `:8080`; `deploy/templates/servicemonitor.yaml` scrapes `/metrics` every 30s.
- `internal/metrics/kusto_logs_current.go:88-92` — `Collect()` is literally `for _, m := range c.cache.GetAll() { ch <- m }`. Everything published is a function of what `CollectMetricValues` wrote into the cache.

## 1. Where the query text lives (NOT in the exporter)
The exporter writes no KQL; it reuses the must-gather machinery.
- `kusto_logs_current.go:94-141`: per cluster in `c.clusterNames` it sets `QueryOptions{InfraClusterName: clusterName, TimestampMin: now−120m, TimestampMax: now, Limit: 100, OrderBy: OrderByDesc}` and builds `mustgather.NewGatherer(queryClient, outputFunc, mustgather.RowOutputOptions{}, GathererOptions{GatherInfraLogs: true, QueryOptions: &queryOptions})`. `RowOutputOptions{}` is empty and `outputFunc` ignores it — the gatherer is used purely as a row pump.
- `GatherInfraLogs: true` makes `Gatherer.GatherLogs` (`tooling/hcpctl/pkg/mustgather/gather.go:329-334`) call `gatherInfraLogs` (`gather.go:527-557`), which builds exactly three definitions by name: `kubernetesEvents`, `systemdLogs`, `infraServiceLogs`.
- Those names resolve via `tooling/hcpctl/pkg/kusto/templates/builtin/queries.yaml` to templates: `infra/kubernetes_events.kql.gotmpl` (`kubernetesEvents | project timestamp, log, cluster | where timestamp between(..) | where cluster == '{{.ClusterName}}' | order by timestamp {{.OrderBy}} | limit {{.Limit}}`), `infra/systemd_logs.kql.gotmpl` (same shape, table `systemdLogs`), and `infra/service_logs.kql.gotmpl` where the table name is the template variable `{{.Table}}`.
- `serviceLogs()` (`tooling/hcpctl/pkg/mustgather/queries.go:21-63`) loops `ServicesTables = [containerLogs, clustersServiceLogs, fleetLogs, frontendLogs, backendLogs]` passing `WithTable(table)` — so five physical tables are each queried, but all with query name `infraServiceLogs`.
- Escaping/normalization: `kusto.NewTemplateDataFromOptions` (`query.go:200-222`) defaults `ClusterName = InfraClusterName`, `TimestampMin/Max` via `kqlDatetime` (UTC), `Limit = max(Limit,0)`, `NoTruncation = Limit < 0`; `WithTable` mutates only template data, never the query name.

## 2. How labels are produced — the marriage (and the one place it's forged)
- `tooling/hcpctl/pkg/kusto/client.go:154`: every row is emitted as `TaggedRow{Row: row, QueryName: query.GetName(), QueryType: ...}`.
- `query.GetName()` returns `templateQuery.name`, set in `Build` (`query.go:300-312`) from **`def.Name` in `queries.yaml`** — NOT from the physical table.
- `Gatherer.convertRows` (`gather.go:627+`) copies that onto `NormalizedLogLine.QueryName` (field list at `gather.go:80-92`), and `outputFunc` (`kusto_logs_current.go:117-128`) does: `key := logLine.QueryName; if _, ok := foundLogSources[key]; !ok { foundLogSources[key] = logLine.Timestamp }` — first row per name wins; with `OrderByDesc` the first row is the newest.
- Publication (`kusto_logs_current.go:147-158`) uses `KustoLogsAgeInSecondsDesc` (`:38-42`): metric `kusto_logs_age_in_seconds`, labels `["kusto_cluster","cluster","table"]`.
  - `table` ← `logSource` (a `foundLogSources` key) ← `QueryName` ← `def.Name`. Emitted values are literally `kubernetesEvents`, `systemdLogs`, `infraServiceLogs` — all five service tables collapse into `infraServiceLogs`.
  - `cluster` ← `clusterName` from `--cluster-names` ← `deploy/values.yaml:26` `"{{ .svc.aks.name }},{{ .mgmt.aks.name }}"` ← `config/config.yaml:524` (`{{env}}-{{region}}-svc-1`, e.g. `dev-westus3-svc-1`) and `:657` (`{{env}}-{{region}}-mgmt-{{stamp}}`).
  - `kusto_cluster` ← `--kusto-cluster` ← `.kusto.kustoName` (e.g. `hcp-dev-us-2`).
- **Genuinely married up**: (a) `cluster` label ↔ `where cluster == '{{.ClusterName}}'` — same string, both ends from `--cluster-names`; (b) `timestamp` column in the KQL projection ↔ `NormalizedLogLine.Timestamp` ↔ metric value; (c) the three label names in the Desc ↔ the three template annotations `{{ $labels.table/cluster/kusto_cluster }}` in the alert.

## 3. The value
`float64(time.Since(foundLogSources[logSource]).Seconds())` — age of the newest row per query name, evaluated at write time.

## 4. Why a disagreement is silent
The only consumer is `observability/alerts/kusto-logs-age-prometheusRule.yaml:13`:
`kusto_logs_age_in_seconds{table!="systemdlogs"} > 3600 or kusto_logs_age_in_seconds{table="systemdlogs",cluster!~".*-svc-.*"} > 3600 or kusto_logs_age_in_seconds{table="systemdlogs",cluster=~".*-svc-.*"} > 7200` (`for: 15m`).
- **Label-text drift**: exporter emits `systemdLogs`, alert matches `systemdlogs`. The `=`/`=~` branches are dead code; because the value falls into `!=` it still fires at 3600s — wrong threshold, no error anywhere. `def.Name` is free text; nothing type-checks it against the matchers. The rule test (`kusto-logs-age-prometheusRule_test.yaml`) feeds hand-written series labels, so it passes regardless of what the exporter actually emits.
- **Five tables → one label**: per-table staleness is invisible; any one healthy table keeps `infraServiceLogs` fresh for all five.
- **Empty result ≠ zero**: no rows → no `cache.Set` → `Collect` emits nothing → `> threshold` is empty → no alert. There is no `absent()` alert for this metric in `observability/`.
- **Errors firewalled from the series**: `GatherLogs` failure only increments `exporter_collector_errors_total` and `continue`s (`:141-145`); that counter has no alert or dashboard consumer in the repo, and the 5m `KustoQueryInterval` dedupe (`:97-99`, using `lastRun` set even on failure) further suppresses retries.

## 5. Why a stale value survives once rows stop arriving (exact timeline)
Config in play: cacheTTL 60m (`values.yaml`, 60× the 1m code default at `options.go:35`), collectionInterval 2m, scrape 30s, lookback 2h, `Limit=100`, `OrderByDesc`, first-row-wins.
Rows stop at time T, last cache write at T:
1. **T → next run (~T+2m)**: `GetAll` (`tooling/metricscache/cache.go:59-72`) returns the entry (age < TTL), so the frozen value is re-served on every 30s scrape. Because the value is computed with `time.Since` at write time, it does NOT grow — a threshold crossing during this window is masked.
2. **Next run**: if the newest row is still within the 2h lookback, a new larger age is written and the series becomes truthful again.
3. **If the query returns no rows or errors**: `cache.Set` is never called and the old entry is left untouched — "queried, empty" and "didn't run" are indistinguishable.
4. **T → T+60m**: frozen value published continuously.
5. **At T+60m**: `GetAll` drops the entry (`now.Sub(created) >= ttl → delete`) and the series disappears entirely.
Net effect: two windows — up to 60 minutes of a frozen (understated) value, then total absence, which the `> threshold`-only alert cannot catch either.

## Deliverable-style summary (no changes made)
If a fix were ever requested, the relevant sites would be: label provenance (`query.go:300-312` naming from `def.Name` vs `WithTable`), per-table fan-in (`mustgather/queries.go:42-63`), empty-result handling (`kusto_logs_current.go:147-158`), value staleness (`cache.go:59-72` + write-time `time.Since`), and alert coverage (`kusto-logs-age-prometheusRule.yaml:13`). I made none of these changes.