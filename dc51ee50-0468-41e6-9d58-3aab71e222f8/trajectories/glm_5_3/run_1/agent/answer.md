I have all the information I need now. Let me compose the final answer. I've traced:

1. Query text in service_tag_usage.go:109-114
2. The struct with no tags (PublicIPAddress) at 102-107
3. mapstructure.Decode at public_ips.go:62
4. IPTag struct with json tags ipTagType/tag at 97-100
5. Desc with labels subscription_id, region, service_tag_type, service_tag_value at 41-46
6. Cache Set at 164-168 with key = labels joined by "/"
7. Cache GetAll with TTL eviction
8. Collect pushes cached metrics
9. values.yaml: cacheTTL 60m, collectionInterval 2m
10. collectLoop sleeps remainder, no error alerting on exporter_collector_errors_total
11. Alert rules divide by hardcoded capacity numbers, `for: 15m`

Let me write the final comprehensive answer now. No more tool calls needed for the analysis. I'll deliver the message and then call finish.

Actually, the instructions say: "If you think you have solved the task, please first send your answer to user through message and then finish the interaction." So I should send my answer in the finish tool's message, or send a message first? The finish tool has a message parameter. I'll put the complete answer in the finish message.

Let me write it carefully and completely.
I have the complete chain traced through every file. No files were modified â this is a strictly read-only investigation.

# The dependency chain: query text â `public_ip_count_by_region_service_tag`

The pipeline matching your incident signature is the **`service-tag-usage`** collector in the **`aro-hcp-exporter`** service. It is the only gauge in this repository where *all four labels and the value* come from columns projected by a query string. (Its sibling `kusto-logs-current` publishes `kusto_logs_age_in_seconds` and shares the identical cache/staleness mechanics â details at the end.)

## The two ends, genuinely married up

**End A â the query text**, `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:109-114`:

```kusto
resources
| where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count()  by  subscriptionId, location, ipTagsString
```

It projects exactly four column names: `subscriptionId`, `location`, `ipTagsString`, `Count`.

**End B â the published series**, `service_tag_usage.go:41-46`:

```go
ServiceTagUsageByPublicIpCountDesc = prometheus.NewDesc(
    "public_ip_count_by_region_service_tag",
    "Number public IP addresses in region by service tag",
    []string{"subscription_id", "region", "service_tag_type", "service_tag_value"},
    nil,
)
```

## Every file in between

1. **`tooling/aro-hcp-exporter/internal/cmd/serve.go`** â `serve.go:38-53` defines `exporter_collector_errors_total{collector}` and `exporter_collector_duration_seconds{collector}`. `Complete()` registers each collector, then `go collectLoop(ctx, collector, o.CollectionInterval)` per collector. `collectLoop` (serve.go:130-160) calls `CollectMetricValues`, records duration, sleeps the remainder of the interval, and on error increments the error counter â then continues looping.

2. **`tooling/aro-hcp-exporter/deploy/values.yaml:23-24`** â `cacheTTL: "60m"`, `collectionInterval: "2m"`, wired as `--cache-ttl=60m --collection-interval=2m` in `deploy/templates/deployment.yaml`. These deployment values override the 1-minute code defaults (`internal/cmd/options.go:34-37`) and stretch the stale window thirty-fold.

3. **`internal/metrics/service_tag_usage.go:129-140`** â `CollectMetricValues` builds the request `{Query: &query, Output: &publicIPs}` and executes it.

4. **`tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go:50-67`** â the *only* place the query text crosses a boundary: `armresourcegraph.QueryRequest{Query: request.Query, Subscriptions: c.subscriptionIDs}`, then `mapstructure.Decode(result.Data, request.Output)`.

5. **`internal/metrics/service_tag_usage.go:102-107`** â the marriage point:

```go
type PublicIPAddress struct {
    Location       string
    IpTagsString   string
    SubscriptionId string
    Count          float64
}
```

6. **`service_tag_usage.go:96-100` + `:116-127`** â `IPTag{ServiceTagType string `json:"ipTagType"`, ServiceTagValue string `json:"tag"`}`; `parseIPTags` runs `json.Unmarshal` on the `ipTagsString` value.

7. **`service_tag_usage.go:163-168`** â labels and value:

```go
labels := []string{publicIP.SubscriptionId, publicIP.Location, ipTag.ServiceTagType, ipTag.ServiceTagValue}
c.cache.Set(strings.Join(labels, "/"), prometheus.MustNewConstMetric(
    ServiceTagUsageByPublicIpCountDesc, prometheus.GaugeValue, publicIP.Count, labels...))
```

8. **`tooling/metricscache/cache.go`** â `Set` stamps `created: time.Now()`; `GetAll` (called by `Collect`, `service_tag_usage.go:90-93`) deletes entries with `now.Sub(e.created) >= ttl`, otherwise returns the metric as-is.

9. **Consumers** â `observability/alerts/service-tag-public-ip-usage.yaml`: each rule selects `service_tag_type="FirstPartyUsage"`, `service_tag_value="/aro-hcp-..."`, divides by hardcoded capacities (32/64/128/18/8), `> 0.8`, `for: 15m`.

## Label-by-label mapping (end A â end B)

| Label | Source in query | Path |
|---|---|---|
| `subscription_id` | `subscriptionId` | mapstructure â `SubscriptionId` â labels[0] |
| `region` | `location` | mapstructure â `Location` â labels[1] |
| `service_tag_type` | inside `ipTagsString` | `json.Unmarshal` key `ipTagType` â `ServiceTagType` â labels[2] |
| `service_tag_value` | inside `ipTagsString` | `json.Unmarshal` key `tag` â `ServiceTagValue` â labels[3] |
| **value** | `Count` (`count()` from `summarize`) | mapstructure â `Count` â `publicIP.Count` |

## Why a disagreement is silent

The two ends are connected by **name matching only**, at `public_ips.go:62`:

- `PublicIPAddress` has **no tags at all**. `subscriptionId`â`SubscriptionId` binds solely via mapstructure's *default case-insensitive field-name matching*.
- `mapstructure.Decode` is called with **no `DecoderConfig`** â no `ErrorUnused: true`, no `ZeroFields`. Consequences:
  - If the query is edited to project `subId` or rename `ipTagsString`, decode **succeeds** with the struct field left at zero value: `subscription_id=""` or `ipTagsString=""`.
  - `IpTagsString == ""` is a *valid* row â `CollectMetricValues` publishes it with `service_tag_type="not-set"`, `service_tag_value="not-set"` (`service_tag_usage.go:152-160` guards only `!= "[]"`). A query-side rename therefore yields **new, well-formed series with `not-set` labels** rather than an error.
  - If `count()` were renamed, `Count` stays `0` and the gauge publishes **0** â which silently *clears* every capacity alert.
- There is no shared contract between the `var query` string and the struct. No test in the repo exercises the query text (`find` shows no `*_test.go` under `aro-hcp-exporter` or `metricscache`). The struct is the only "documentation" of expected columns, and it is tagless.
- Registry-side, `Describe` emits one `Desc` unconditionally (`service_tag_usage.go:79-81`), so the collector appears healthy even when it publishes nothing.
- `exporter_collector_errors_total` counts only *transport/parse* failures. A successful decode of a mismatched column set increments nothing, and there is **no alert anywhere on `exporter_collector_errors_total`** (`grep` over `observability/` returns nothing).

Note also the alert-side vocabulary: test fixtures use `service_tag_type="FirstPartyUsage"` while real IP tags carry `ipTagType` values like `RoutingPreference`/`FirstPartyUsage` â the literal string in the alert must equal the JSON `ipTagType` verbatim; any drift there also fails silently (empty vector, no alert).

## Why a stale value survives after rows stop arriving

Suppose a public IP is deleted, or the Resource Graph response stops including a `(subscription, location, tag)` combination:

1. The row simply stops appearing in `result.Data` â there is no delete/tombstone. The old cache entry is *never overwritten*, because `Set` is only called for rows that arrived.
2. `GetAll()` (`cache.go`) evicts only when `now.Sub(e.created) >= ttl`. With the **deployed `cacheTTL: "60m"`**, the last-seen value is still served on `/metrics` for up to **60 minutes**.
3. The value is a `prometheus.GaugeValue` captured at write time. Unlike a counter, a held gauge looks like a healthy current reading; Prometheus scrapes the same frozen number repeatedly, so the series does not even look flat-lined from a distance.
4. The capacity alerts require the *ratio* to exceed 0.8 for 15 minutes â a stale value above threshold will genuinely page; a stale value *below* threshold masks a genuine spike for the full TTL window.
5. `collectLoop` sleeps the interval remainder and never alerts on "zero rows decoded" â an empty result set is indistinguishable from a no-change result set.

## The sibling: `kusto_logs_age_in_seconds` (same skeleton)

- Value = `float64(time.Since(foundLogSources[logSource]).Seconds())` (`kusto_logs_current.go:147-158`) â computed once at collect time, frozen into the cache.
- Labels `kusto_cluster`/`cluster`/`table`: `table` = `logLine.QueryName`, i.e. the **built-in definition name** from `hcpctl/pkg/kusto/templates/builtin/queries.yaml` (e.g. `infraServiceLogs`, `systemdLogs`, `kubernetesEvents`), not the physical table. It flows `query.GetName()` â `TaggedRow.QueryName` (`client.go:154`) â `NormalizedLogLine.QueryName` (`gather.go:627-655`) â `foundLogSources` map â `cache.Set(key, ...)` with key `kustoCluster/clusterName/logSource`.
- Templates: `infra/service_logs.kql.gotmpl` uses `{{.Table}}` where `Table` comes from `ServicesTables` (`queries.go:21-27`) via `WithTable`; `infra/systemd_logs.kql.gotmpl` and `infra/kubernetes_events.kql.gotmpl` are hardcoded to tables `systemdLogs` / `kubernetesEvents`. Column contract (`timestamp, log, cluster, namespace_name, container_name`) is bound by kusto struct tags on `NormalizedLogLine` (`gather.go:81-88`) and matched by name in `convertRows`.
- `Timestamp` binds via tag `kusto:"timestamp"` â the query templates' `| project timestamp, ...` is the same tagless-name-matching hazard; a template rename silently zeroes `foundLogSources` entries.
- Extra staleness: the collector self-throttles with `KustoQueryInterval = 5 * time.Minute` (`kusto_logs_current.go:34, 97-99`) *and* the cache TTL is 60m *and* the `table` label only exists if rows arrived. If a source stops emitting, no rows â no `Set` â the frozen gauge is served until the 60m TTL evicts it; the age alert (`kusto_logs_age_in_seconds > 3600`, `for: 15m`) cannot rise until a *new* row exists to timestamp. Meanwhile the value never updates to reflect continued aging, because it was computed once at collect time.

## Summary

- The query text and the metric are married **only** at `mapstructure.Decode` (`public_ips.go:62`) against a **tagless** struct, with **no `ErrorUnused`** â any query-side column rename decodes "successfully" into zero values or new `not-set` series, with no error and no alert (`exporter_collector_errors_total` is un-alerted, and a clean decode doesn't touch it anyway).
- A stale value survives because `Set` only ever *adds/overwrites by label key*; disappearance of a row produces no tombstone, and `GetAll` evicts on `created + ttl` with the **deployed TTL of 60 minutes** (`values.yaml:23`), serving a frozen gauge value that looks live.
- There is no test anywhere on this chain (no `_test.go` under `aro-hcp-exporter`/`metricscache`), which is why such drift reaches production unnoticed.

I traced the full dependency chain for the query-text-driven gauge. Findings:

**The pipeline**: `service-tag-usage` collector in `aro-hcp-exporter`, publishing `public_ip_count_by_region_service_tag`.

**The chain, file by file**:
1. `deploy/values.yaml` (cacheTTL 60m, collectionInterval 2m) â deployment args
2. `internal/cmd/serve.go` â collectLoop per collector; error counter + duration histogram; no alert on the error counter
3. `internal/metrics/service_tag_usage.go:109-114` â the KQL/ARG query text projecting `subscriptionId`, `location`, `ipTagsString`, `Count`
4. `pkg/graphquery/public_ips.go:50-67` â executes query, then `mapstructure.Decode(result.Data, &request.Output)` with NO DecoderConfig (no ErrorUnused)
5. `internal/metrics/service_tag_usage.go:102-107` â `PublicIPAddress` struct with NO tags; binding relies solely on mapstructure case-insensitive name matching
6. `:96-100,116-127` â `IPTag` json tags `ipTagType`/`tag` unmarshal `ipTagsString`
7. `:41-46` Desc labels `subscription_id, region, service_tag_type, service_tag_value`; `:163-168` value = `publicIP.Count`
8. `tooling/metricscache/cache.go` â Set stamps time; GetAll evicts at `created+ttl`
9. `observability/alerts/service-tag-public-ip-usage.yaml` â consumer, hardcoded divisors, `for: 15m`

**Why disagreements are silent**: tagless struct + `mapstructure.Decode` without `ErrorUnused` means a query rename decodes into zero values / `not-set` labels with success status; empty ipTagsString is a valid row publishing `not-set` labels; `Describe` always succeeds; no tests exist on the chain; no alert on `exporter_collector_errors_total`; and the alert's label literals must match `ipTagType` verbatim.

**Why stale values survive**: `Set` only fires for rows that arrived â no tombstone on disappearance; eviction waits for `created + 60m` (deployed TTL); the gauge value is frozen at write time so it looks like a live reading; collectLoop sleeps on, and an empty result set is indistinguishable from "no change".

**Sibling** `kusto_logs_age_in_seconds` shares the same cache skeleton with extra staleness: 5m self-throttle, 60m TTL, and a missing `table` series when rows stop arriving, so the age alert cannot escalate until a new row appears.

No files were modified; this was strictly read-only.