I've completed the investigation. Everything below is from the actual source; I changed nothing.

# The dependency chain: `public_ip_count_by_region_service_tag`

The gauge is published by the **`aro-hcp-exporter`** service (`tooling/aro-hcp-exporter`), and the "query" is an **Azure Resource Graph (KQL)** string, not SQL.

### Stage 1 — Query text with projected columns
`tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:109-114`

```kusto
resources
| where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count() by subscriptionId, location, ipTagsString
```

The projected columns are **`subscriptionId`**, **`location`**, **`ipTagsString`**, **`Count`**.

### Stage 2 — The projection target (an untagged struct)
`service_tag_usage.go:102-106`

```go
type PublicIPAddress struct {
    Location      string
    IpTagsString  string
    SubscriptionId string
    Count         float64
}
```

There are **no struct tags at all** on these fields — no `mapstructure:"..."`, no `json:"..."`. Binding relies purely on exported field names.

### Stage 3 — The single marriage point
`tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go:53-65`, `ExecuteConvertRequest` sends the query and then, at **line 62**:

```go
err = mapstructure.Decode(result.Data, &request.Output)
```

This is the **only place in the entire codebase** where the query's column names and the Go type meet. ARG returns `objectArray` (`[]map[string]any`); `mapstructure` with **default config** matches map keys to field names case-insensitively. Unmatched keys are dropped, unmatched fields stay at their Go zero value, and **`err` stays `nil`**.

### Stage 4 — Labels and value
`service_tag_usage.go:41-46` declares the Desc with label names `subscription_id, region, service_tag_type, service_tag_value`. `service_tag_usage.go:97-99` decodes the nested tag JSON:

```go
type IPTag struct {
    ServiceTagType  string `json:"ipTagType"`
    ServiceTagValue string `json:"tag"`
}
```

`service_tag_usage.go:162-169` binds **positionally**:

```go
labels := []string{publicIP.SubscriptionId, publicIP.Location, ipTag.ServiceTagType, ipTag.ServiceTagValue}
c.cache.Set(strings.Join(labels, "/"), prometheus.MustNewConstMetric(
    ServiceTagUsageByPublicIpCountDesc, prometheus.GaugeValue, publicIP.Count, labels...))
```

So the full contract is: **query column → struct field (via unvalidated name match) → positional element of `labels` → label name in the Desc**. Only the last two links are machine-checked (`MustNewConstMetric` panics on arity/type mismatch); the column-to-field link has no check whatsoever. This is exactly where a query rename "projects" into nothing.

### Stage 5 — Publication
`tooling/aro-hcp-exporter/internal/cmd/serve.go:130-143` runs `collectLoop`, calling `CollectMetricValues` every `collectionInterval`; `service_tag_usage.go:91-93` serves `cache.GetAll()` on every `/metrics` scrape. Deployed values (`deploy/values.yaml`, `deployment.yaml`, `servicemonitor.yaml`): **`cacheTTL: "60m"`, `collectionInterval: "2m"`, scrape `interval: 30s`**.

# Why a disagreement is completely silent

Say `ipTagsString` is renamed in the query (e.g. to `ipTags`):

1. ARG happily returns rows. `mapstructure.Decode` (`public_ips.go:62`) runs with default config — no `ErrorUnused`, no `ZeroFields`. `IpTagsString` is left `""` and **`err` is `nil`**, so `return nil, nil` at the top of `CollectMetricValues` and the `errorCounter.Inc()` / `logger.Error` failure branch (lines ~138-141) are **never reached**. `exporter_collector_errors_total` does not move.
2. `if publicIP.IpTagsString != ""` at line ~151 skips the row; `parseIPTags("")` isn't even called — and even if it were, it returns an **empty slice, not an error**.
3. The inner `for _, ipTag := range ipTags` loop body never executes, so **`cache.Set` is never called and nothing is deleted**. The exporter returns 200 with a full `/metrics` payload — just without this family (or with zero-valued labels if a different column drifts).
4. On the consuming side, `observability/alerts/service-tag-public-ip-usage.yaml` has **10 rules that are all pure threshold comparisons** (`public_ip_count_by_region_service_tag{...} / N > 0.8`) with `for: 15m`. An absent series evaluates to nothing — the alerts simply **stop having an opinion**. There is **no `absent()` rule** for this metric anywhere in `observability/` or `dev-infrastructure/modules/metrics/rules/`, no staleness/`time()`-based rule, and no alert on `exporter_collector_errors_total` (which wouldn't fire anyway).
5. There are **zero unit tests** in `tooling/aro-hcp-exporter`, `tooling/metricscache`, or `tooling/hcpctl/pkg/mustgather`. The only tests are `service-tag-public-ip-usage_test.yaml` promtool rule tests, which hand-craft the series and therefore can never catch a producer-side rename.

Notably, the repo's *other* exporter collector (`kusto_logs_current`) does have a staleness alert (`KustoLogsDataStale`, `kusto_logs_age_in_seconds > 3600`) — so the pattern is known but not applied to this gauge, which has no timestamp label to hang it on.

# Why a stale value survives for a period once rows stop arriving

`tooling/metricscache/cache.go`:

- `Set` (line ~52) is the **only writer** and is only reached from a successfully projected row.
- `GetAll` (lines ~59-69) only deletes entries when `now.Sub(e.created) >= c.ttl`; otherwise it returns the cached `prometheus.Metric` — the **frozen value and labels from the last successful cycle**.
- **Nothing invalidates on failure.** A failed or empty projection neither writes nor clears; the failure path never touches the cache.

With `cacheTTL=60m` but `collectionInterval=2m`, the last good value is replayed on roughly **120 consecutive scrapes (30s each) across ~30 collection cycles** — every one of them indistinguishable from fresh data, since a const metric carries no timestamp. Only after 60 minutes do entries age out and the series go absent — at which point, per the previous section, the alerts silently lose their input rather than firing. Prometheus's own staleness marking never engages during that window because the series keeps appearing in every scrape.

### Summary of the fragility
The query column names, the untagged `PublicIPAddress` fields, the positional `labels` slice, and the Desc's label names form a four-way agreement with validation only on the final link. `mapstructure`'s default leniency (no `ErrorUnused`, zero-value fallback, case-insensitive matching) converts any upstream rename into a no-op rather than an error, the TTL cache then extends the last good sample for an hour, and the alerting rules are threshold-only with no absence guard — so the breakage is invisible end to end.

Let me write the final comprehensive answer now. I have all the facts I need. Let me compose it carefully and completely, then call finish.
I have everything needed. Here is the complete read-only analysis.

## The chain: query text → labels → value

**Metric:** `public_ip_count_by_region_service_tag`, published by `aro-hcp-exporter` (`tooling/aro-hcp-exporter`), backed by an **Azure Resource Graph (KQL)** query — not SQL.

**File 1 — `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go`**

Query (lines 109–114):
```kusto
resources | where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count() by subscriptionId, location, ipTagsString
```
Projected columns: `subscriptionId`, `location`, `ipTagsString`, `Count`.

Projection target (lines 102–106) — note **no struct tags at all**:
```go
type PublicIPAddress struct {
    Location string
    IpTagsString string
    SubscriptionId string
    Count float64
}
```

**File 2 — `tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go`** (lines 53–65)

`ExecuteConvertRequest` sends the query and, at **line 62**, performs the projection:
```go
err = mapstructure.Decode(result.Data, &request.Output)
```
This is the **only place in the codebase** where the query's column names and the Go type meet. ARG returns `objectArray` (`[]map[string]any`); `mapstructure` with its default config matches map keys to **exported field names, case-insensitively**. Renaming a column (`ipTagsString` → `ipTags`) leaves the field at its Go zero value while `err` stays `nil`.

**File 3 — back to `service_tag_usage.go`**

`IPTag` (lines 97–99) decodes the nested tag JSON with real tags — this is the contrast that proves the outer level is fragile:
```go
type IPTag struct {
    ServiceTagType  string `json:"ipTagType"`
    ServiceTagValue string `json:"tag"`
}
```
Lines 41–46 declare label names; lines 162–169 bind them **positionally** and set the value:
```go
labels := []string{publicIP.SubscriptionId, publicIP.Location, ipTag.ServiceTagType, ipTag.ServiceTagValue}
c.cache.Set(strings.Join(labels, "/"),
    prometheus.MustNewConstMetric(ServiceTagUsageByPublicIpCountDesc, prometheus.GaugeValue, publicIP.Count, labels...))
```
So the contract is: **query column → struct field (unvalidated name match) → positional `labels` element → label name in the Desc → `Count` as the gauge value.** The positional/arity link is machine-checked by `MustNewConstMetric`; the column-to-field link is checked by nothing.

**File 4 — publication.** `internal/cmd/serve.go` runs `collectLoop` (calls `CollectMetricValues` every `collectionInterval`); `service_tag_usage.go:91-93` `Collect` serves `cache.GetAll()` on every `/metrics` scrape. Deployed: `cacheTTL: "60m"`, `collectionInterval: "2m"`, ServiceMonitor scrape `interval: 30s`.

## Why a disagreement is silent

With `ipTagsString` renamed in the query:
1. ARG still returns rows; `mapstructure.Decode` returns `nil` — unmatched keys/columns are simply skipped (zero values, no error).
2. `errorCounter.Inc()` (`exporter_collector_errors_total`) is on the error path only — never incremented. No log line.
3. `if publicIP.IpTagsString != ""` fails, `parseIPTags("")` returns an empty slice, the `ipTags` fallback keeps `not-set`/`not-set`, and `Count` (0) — so a zero-valued row is **published with success signals**, not an error.
4. The cache, error counter, duration histogram, and logs all look healthy.
5. All 10 consumers in `observability/alerts/service-tag-public-ip-usage.yaml` (and `dev-infrastructure/.../generatedPrometheusAlertingRules.bicep`) are threshold ratios (`... / 32 > 0.8`) — a **missing or zero series simply never fires**, and `for: 15m` is moot. No `absent()` rule exists anywhere for this metric, and there are **zero unit tests** for the exporter, the collector, the cache, or the decode path.

## Why a stale value survives once rows stop arriving

`tooling/metricscache/cache.go`: `Set` is the **only writer**; `GetAll` deletes only when `now.Sub(e.created) >= ttl` and otherwise returns the frozen metric. Failed or empty collections **never invalidate** — the failure path never touches the cache. With `cacheTTL=60m`, the last good value is replayed across ~120 scrapes and ~30 collection cycles (with no metric timestamp, so Prometheus timestamps it as fresh each scrape), and the capacity alerts keep evaluating the dead value. Only after 60 minutes do entries age out — and then the series vanishes silently rather than alerting.

No files were modified at any point.

Traced the full dependency chain for the published gauge `public_ip_count_by_region_service_tag` from `aro-hcp-exporter`. The query is Azure Resource Graph KQL in `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:109-114`, projected into the untagged `PublicIPAddress` struct (lines 102-106) by `mapstructure.Decode` at `tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go:62` — the single, unvalidated marriage point between query column names and Go fields. Labels are bound positionally at lines 162-169 against the Desc's label names, with `Count` as the value; publication flows through `serve.go`'s collect loop and `metricscache.Cache`. A column rename is silent because mapstructure leaves unmatched fields at zero values with a nil error, the error counter sits on the unreachable error path, empty tag strings fall through to a `not-set` zero-valued metric, and the downstream capacity alerts are pure threshold ratios with no absent() guard. Staleness persists because `Cache.GetAll` is age-based only (TTL 60m vs 2m collection interval and 30s scrape), so the last good value is replayed as fresh for up to an hour after rows stop arriving. Strictly read-only: no files were created, edited, or deleted, and no state was mutated.