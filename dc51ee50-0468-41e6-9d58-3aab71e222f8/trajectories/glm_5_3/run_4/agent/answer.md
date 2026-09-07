I have completed the read-only investigation. Here is the full dependency chain, traced in the actual source.

---

# The two ends

**Query end:** the inline Azure Resource Graph (KQL) string in `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:107-114`:

```kusto
resources
| where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count()  by  subscriptionId, location, ipTagsString
```

**Series end:** the gauge `public_ip_count_by_region_service_tag{subscription_id, region, service_tag_type, service_tag_value}`, declared at `service_tag_usage.go:41-46` and served at `/metrics` every 30s (`tooling/aro-hcp-exporter/deploy/templates/servicemonitor.yaml`).

# The chain, hop by hop

| # | File / line | What happens |
|---|---|---|
| 1 | `service_tag_usage.go:107-114` | Query projects 4 columns. |
| 2 | `pkg/graphquery/public_ips.go:50-65` | `armresourcegraph.Client.Resources` runs it against subscription IDs resolved from *names* by `tooling/azutils/subscriptions/resolver.go:109` (fed by `deploy/values.yaml`); then `mapstructure.Decode(result.Data, &request.Output)`. |
| 3 | `service_tag_usage.go:101-106` | `PublicIPAddress{Location, IpTagsString, SubscriptionId string; Count float64}` — **zero struct tags**. |
| 4 | `service_tag_usage.go:96-99, 116-127` | `json.Unmarshal(IpTagsString)` into `IPTag{ServiceTagType \`json:"ipTagType"\`; ServiceTagValue \`json:"tag"\`}`; `"[]"` → synthetic `not-set`/`not-set`; empty string → **zero series**. |
| 5 | `service_tag_usage.go:163-169` | `labels := []string{SubscriptionId, Location, ServiceTagType, ServiceTagValue}` → `prometheus.MustNewConstMetric(Desc, GaugeValue, Count, labels...)`. |
| 6 | `tooling/metricscache/cache.go:52-72` | `Set(key, metric)`; `GetAll()` returns everything younger than TTL. |
| 7 | `internal/cmd/options.go:134-139`, `internal/cmd/serve.go:130-151` | Collector registered on a private registry; `collectLoop` runs `CollectMetricValues` every interval, **discarding its result**. |

# Where the two ends are genuinely married up

Three marriages, each fragile in a different way:

1. **KQL column name → Go field name** (`:107-114` ↔ `:101-106`). Held together *solely* by mapstructure's default case-insensitive field matching: `subscriptionId`→`SubscriptionId`, `location`→`Location`, `ipTagsString`→`IpTagsString`, `Count`→`Count`. No tag, no compile-time check, no runtime check. **This is the marriage your rename breaks.**
2. **`ipTags` JSON keys → `IPTag` json tags** (`:96-99`). The only explicit binding in the chain — renaming `ipTagType`/`tag` in the JSON is the one rename that fails *loudly* (unmarshal error → `errorCounter.Inc()` + error log).
3. **Label values → `Desc` label names** (`:41-46` ↔ `:163-169`). `MustNewConstMetric` binds **by position**; it panics only on a *count* mismatch, never on emptiness or wrongness. Cache key = `strings.Join(labels, "/")`, also derived from the same values.

# What exactly breaks when you rename a projected field

Let's say `subscriptionId` → `subscription_id`. The query still succeeds — ARG doesn't care what you call a column; the `summarize ... by` still yields rows with `Count` populated. Then:

- `mapstructure.Decode` returns **nil**. `ErrorUnused` is off by default, and even if it weren't, `Count` still matches. Unmatched source keys are silently dropped.
- With no tag, `WeaklyTypedInput`/name matching finds no field for `subscription_id` → `SubscriptionId` stays `""`.
- `IpTagsString` still decodes, tags still parse, so the loop *runs* and calls `c.cache.Set` — with key `"/eastus/FirstPartyUsage/..."` and label value `""`.
- Net effect: **every series is republished under a new label set (`subscription_id=""`) and a new cache key**. From Prometheus's point of view the old series vanish and a new family appears. Nothing errors.

Rename `location` or `ipTagsString` instead and you get slightly different flavors of the same silence — including, for `ipTagsString`, `parseIPTags("")` returning an empty slice so the inner loop emits **no series at all**. Renaming `Count` alone would silently publish value `0`.

# Why the disagreement is completely silent

Five independent reasons, each sufficient on its own:

1. `mapstructure.Decode` never errors on unmatched keys.
2. `MustNewConstMetric` validates label **count**, not content.
3. `c.errorCounter.Inc()` (→ `exporter_collector_errors_total{collector="service-tag-usage"}`) sits on the two paths that *can* fail, and a rename reaches neither. And **no alert anywhere in the repo references `exporter_collector_errors_total`** — even a genuine query failure only logs and increments a metric nobody watches.
4. `collectLoop` (`serve.go:141`) discards the return of `CollectMetricValues` and sleeps; the interface (`internal/metrics/collector.go`) has no error return at all.
5. `observability/alerts/service-tag-public-ip-usage.yaml` has **no `absent()` rule** (verified: 0 occurrences). Ten capacity alerts, all `count / capacity > 0.8` with `for: 15m`. An empty vector is neither > 0.8 nor pending, so all ten simply go quiet.

Bonus silence: those alerts' annotations use `{{ $labels.cluster }}`, but the `Desc` declares no `cluster` label — so even when they do fire, the text renders empty. The rule *test* fixtures (`observability/alerts/service-tag-public-ip-usage_test.yaml`) also carry a `cluster` label the exporter never emits, which is why the tests can't catch this.

# Why a stale value survives after rows stop arriving

The decisive config is `tooling/aro-hcp-exporter/deploy/values.yaml`:

```yaml
cacheTTL: "60m"
collectionInterval: "2m"
```

…while `DefaultCacheTTL`/`DefaultCollectionInterval` in `options.go` are both **1m**. So the deployed TTL is 60× the code default and 30× the scrape interval.

Mechanics in `tooling/metricscache/cache.go`:
- `Set` stores `{metric, created: time.Now()}` where `metric` is an **immutable const metric** — the gauge value is frozen at write time, never recomputed on scrape.
- `GetAll` returns every entry with `now.Sub(created) < ttl`, deleting the rest.
- **`GetAll` is the only thing that evicts**, and it is only called from `Collect` — i.e. only when a scrape happens.

So while the exporter still returns *some* rows (which is exactly the rename case: rows arrive, labels empty), the surviving series keep serving their frozen values for up to **60 minutes** — 30 consecutive scrapes of identical, increasingly meaningless numbers. Even in the total-failure case, an empty result never clears the cache; it only stops refreshing it, so old entries still serve until each one individually crosses its 60-minute birthday.

That is precisely the incident you describe: "for a good while after collection had already stopped yielding rows the previous numbers were still being handed to every scrape."

# Contrast that proves the point

The *other* gauge in the same binary, `kusto_logs_age_in_seconds` (`kusto_logs_current.go`), is loud by construction. Its KQL templates (`tooling/hcpctl/pkg/kusto/templates/builtin/**`) use `project timestamp, log, cluster, namespace_name, container_name`, and `mustgather.NormalizedLogLine` (`tooling/hcpctl/pkg/mustgather/gather.go:80-90`) binds them with **explicit `` `kusto:"..."` `` tags**. Rename `timestamp` there and the field silently stays at the zero `time.Time` — which makes `time.Since(...)` huge, which trips `kusto_logs_age_in_seconds > 3600` in `observability/alerts/kusto-logs-age-prometheusRule.yaml`. A mismatch becomes a *wrong value that an alert catches*. On the service-tag gauge, a mismatch becomes an *absent series that nothing catches*.

# Summary of blast radius

- `service_tag_usage.go:107-114` — query text: rename here is the trigger.
- `service_tag_usage.go:101-106` — the struct that must be renamed **in lockstep** (or, better, given explicit `mapstructure:"..."` tags, which would make this a compile/grep-visible contract).
- `service_tag_usage.go:41-46` and `:163-169` — label names/values, affected if the renamed column feeds a label.
- `observability/alerts/service-tag-public-ip-usage.yaml` — ten alerts that go dark with no `absent()` backstop; annotations also reference a nonexistent `cluster` label.
- `deploy/values.yaml` (`cacheTTL: 60m`) vs `options.go` (1m default) — the reason stale values persist ~60 minutes.
- No unit tests exist for `aro-hcp-exporter`, `metricscache`, or `graphquery` — nothing in CI can catch this.

If you want the change to be safe, the guards I'd consider (not applied, read-only task) are: explicit `mapstructure` tags on `PublicIPAddress`; a "no series produced" check that increments the error counter; an `absent()` alert on `public_ip_count_by_region_service_tag`; and reducing `cacheTTL` or adding a `last_success` timestamp gauge so staleness is observable.

I have completed the full investigation. Let me write the final answer message now, then call finish properly. The finish tool requires message and task_completed parameters. Let me deliver the complete analysis in the message and then call finish.
The investigation is complete. Here is the full traced chain, the marriages, the silence mechanisms, and the staleness mechanics — strictly read-only, nothing changed.

# The metric: `public_ip_count_by_region_service_tag`

Published by the **ARO-HCP exporter** (`tooling/aro-hcp-exporter`), gauge with labels `subscription_id, region, service_tag_type, service_tag_value`.

## The dependency chain, hop by hop

**Hop 1 — Query text**: `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:107-114`
```kusto
resources
| where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count() by subscriptionId, location, ipTagsString
```
One row per distinct `(subscriptionId, location, ipTagsString)`; `Count` = public IPs in that bucket; `ipTagsString` = the resource's `properties.ipTags` JSON array as a string.

**Hop 2 — Transport + decode**: `pkg/graphquery/public_ips.go:50-65`. `armresourcegraph.Client.Resources(...)` runs the query scoped to subscription IDs resolved from names (`tooling/azutils/subscriptions/resolver.go:109`), then `mapstructure.Decode(result.Data, &request.Output)`.

**Hop 3 — First marriage (implicit, name-based only)**: `service_tag_usage.go:101-106`
```go
type PublicIPAddress struct {
    Location       string
    IpTagsString   string
    SubscriptionId string
    Count          float64
}
```
**The struct has zero tags.** The KQL column → field binding is purely mapstructure v2's default *case-insensitive field-name matching*: `subscriptionId`→`SubscriptionId`, `location`→`Location`, `ipTagsString`→`IpTagsString`, `Count`→`Count`. Nothing in the repo enforces this.

**Hop 4 — Second marriage (explicit, JSON tags)**: `service_tag_usage.go:96-99, 116-127`. `json.Unmarshal(IpTagsString)` into `IPTag{ServiceTagType `json:"ipTagType"`; ServiceTagValue `json:"tag"`}` — the only explicit binding in the whole chain. `"[]"` yields a synthetic `not-set`/`not-set` tag; `""` yields none.

**Hop 5 — Third marriage (positional)**: `service_tag_usage.go:163-169`. `labels := []string{SubscriptionId, Location, ServiceTagType, ServiceTagValue}` passed to `MustNewConstMetric(Desc, GaugeValue, publicIP.Count, labels...)`. The `Desc` (`:41-46`) declares `{"subscription_id","region","service_tag_type","service_tag_value"}`. Binding is **by position**; the cache key is `strings.Join(labels, "/")`.

**Hop 6 — Publication**: `Collect` drains `cache.GetAll()`; registered via `internal/cmd/options.go:134-139`; scraped every **30s** (`deploy/templates/servicemonitor.yaml`).

## Why a disagreement is silent

1. `mapstructure.Decode` returns nil on unmatched columns; `ErrorUnused` is off.
2. `MustNewConstMetric` only panics on label *count* mismatch — never emptiness or wrongness.
3. The `CollectMetricValues` error path (`c.errorCounter.Inc()` at `:140`) fires only on transport/parse errors, not on column drift.
4. `collectLoop` (`internal/cmd/serve.go:130-151`) ignores the outcome entirely.
5. No `absent()` rule exists for this metric (0 occurrences), and **nothing alerts on `exporter_collector_errors_total`** anywhere.
6. No unit tests exist for the exporter, `metricscache`, or `graphquery`.

**Scenario matrix**: renaming `subscriptionId` or `location` re-labels every series (old ones vanish silently); renaming `ipTagsString` makes `parseIPTags("")` return nothing ⇒ **no series at all**; renaming `Count` publishes `0`. In every case, the only observable would be a missing/renamed series that nothing catches. Contrast: the sibling `kusto_logs_age_in_seconds` chain uses explicit `kusto:"..."` struct tags (`mustgather/gather.go:80-90`) against `project timestamp, log, cluster...` — a rename there yields a wrong *value* that the `> 3600` alert (`observability/alerts/kusto-logs-age-prometheusRule.yaml`) catches.

Also noteworthy: the alert annotations use `{{ $labels.cluster }}`, a label this metric does not have — it renders empty.

## Why a stale value survives

From `deploy/values.yaml`: `cacheTTL: "60m"`, `collectionInterval: "2m"`, scrape 30s (code defaults in `options.go` are 1m each). In `tooling/metricscache/cache.go`: `Set` stores `{metric, created: now}` where the metric is an **immutable frozen snapshot**; `GetAll` (the *only* eviction path, called only on scrape) returns entries with `now.Sub(created) < ttl`. On query failure, `CollectMetricValues` returns early without touching the cache — so **the last good value is republished for up to 60 minutes** while `exporter_collector_errors_total` ticks up unwatched. The Kusto collector has an extra guard (`lastRun` + 5m `KustoQueryInterval`) and its own 60m cache, with the same silence property.

Read-only investigation complete. The chain tying query text to labels/value for public_ip_count_by_region_service_tag: (1) inline ARG/KQL query at tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go:107-114 projecting subscriptionId, location, ipTagsString, Count; (2) graphquery/public_ips.go:50-65 executes it via armresourcegraph and decodes with mapstructure.Decode into an untagged PublicIPAddress struct (service_tag_usage.go:101-106) — a purely name-based, unenforced marriage; (3) ipTagsString parsed via explicit json tags into IPTag (:96-99,116-127); (4) labels bound positionally to the Desc's subscription_id/region/service_tag_type/service_tag_value and the value Count frozen into an immutable const metric (:163-169); (5) served from a TTL cache. A disagreement is silent because mapstructure never errors on unmatched columns, MustNewConstMetric only checks label count, the error counter is incremented only on transport/parse failures, the collect loop ignores results, and there is no absent() alert and no alerting on exporter_collector_errors_total (no unit tests either). A stale value survives because cacheTTL=60m vs 2m collection vs 30s scrape: on failure CollectMetricValues returns early leaving the cache untouched, and GetAll (the only eviction path, driven by scrapes) keeps returning the frozen snapshot for up to 60 minutes. Contrast: the kusto_logs_age_in_seconds chain uses explicit kusto struct tags and a >3600s alert, so a mismatch there surfaces as a wrong value rather than a missing series.