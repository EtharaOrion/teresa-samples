I've done the full investigation. Now I need to write the final answer as my deliverable in prose. No changes made — read-only investigation. Let me compose the complete answer covering:

1. The dependency chain traced in code
2. Where the two ends are married up (the query text and the metric labels/value)
3. What makes a disagreement silent
4. Why a stale value survives for a period once rows stop arriving

Let me write it out carefully with file paths and line references.
I've completed the read-only investigation. Nothing in the repository was modified.

---

# What I traced: the `public_ip_count_by_region_service_tag` chain

The tightest "query text ↔ published series" coupling in this repo lives in the **aro-hcp-exporter**, under `tooling/aro-hcp-exporter/`. Everything below is one collector's path from KQL text to a Prometheus series with four labels and a numeric value.

## The real dependency chain, file by file

1. **`tooling/aro-hcp-exporter/internal/cmd/options.go`** — `Complete()` builds the collector set from the `--enabled-collectors` flag; `service-tag-usage` is one of the two defaults. (Aside, noted but not acting on it: line 136 reads `if registry.Register(collector) != nil { ... "%w", err }` using the *outer* `err` rather than the value `Register` returned — a shadowing bug that would mis-report a registration failure.)

2. **`tooling/azutils/subscriptions/`** — `ResolveByName` turns the `--subscription-names` values (svc + mgmt subscription names) into subscription GUIDs. This is the source of the `subscription_id` label.

3. **`tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go`** — `ResourceGraphClient.ExecuteConvertRequest` sends the query string to Azure Resource Graph and then calls **`mapstructure.Decode(result.Data, &request.Output)`** (go-viper/mapstructure v2.5.0). It returns the decode error and nothing else — no `ErrorUnused`, no `Metadata` inspection.

4. **`tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go`** — the marriage point. Three things sit in one file:
   - The **query text** (`var query`, ~line 105) projects exactly four named columns:
     ```kql
     resources
     | where type == 'microsoft.network/publicipaddresses'
     | extend ipTagsString = tostring(properties['ipTags'])
     | summarize Count=count() by subscriptionId, location, ipTagsString
     ```
   - The **decode target**, `PublicIPAddress { Location, IpTagsString, SubscriptionId string; Count float64 }` — with **no `mapstructure:` or `json:` tags**.
   - The **metric description** `ServiceTagUsageByPublicIpCountDesc` = `public_ip_count_by_region_service_tag`, labels `["subscription_id", "region", "service_tag_type", "service_tag_value"]`.

5. **`tooling/metricscache/cache.go`** — `Set` stamps `created: time.Now()`; `GetAll` lazily expires entries past TTL *only when scraped*.

6. **`tooling/aro-hcp-exporter/internal/cmd/serve.go`** — `collectLoop` calls `CollectMetricValues` every `--collection-interval`; `promhttp` calls `Collect` on every scrape.

7. **`tooling/aro-hcp-exporter/deploy/values.yaml` + `templates/deployment.yaml` + `templates/servicemonitor.yaml`** — `cacheTTL: "60m"` (the code default is 1m, the deployment overrides it to 60m), `collectionInterval: "2m"`, ServiceMonitor scrape `interval: 30s`.

8. **`observability/alerts/service-tag-public-ip-usage.yaml`** and its compiled form `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep` — the consumers: `public_ip_count_by_region_service_tag{service_tag_type="FirstPartyUsage", service_tag_value="/aro-hcp-prod-inbound-svc"} / 32 > 0.8` etc. The IP tag strings (`FirstPartyUsage`, `/aro-hcp-prod-inbound-*`) are also documented in `docs/ingress-egress.md` and enumerated in `config/config.schema.json` — so a fourth copy of the coupling exists in the alert rule text itself.

## Where the two ends are genuinely married up

The KQL column names in step 4 and the Go field names in step 4 are **married by string equality only**, enforced by mapstructure's default *case-insensitive Go-field-name* matching: `subscriptionId`→`SubscriptionId`, `location`→`Location`, `Count`→`Count`, `ipTagsString`→`IpTagsString`. There is no schema, no shared constant, and no tag declaring the link — the contract is implicit in two adjacent identifiers. The label names (`subscription_id`, `region`, …) are then married to the alert rule text by a third implicit string match in the YAML.

## What makes a disagreement silent

Consider any divergence between the query's projected columns and the struct — e.g. someone renames `Count` to `PublicIpCount` in the KQL, or renames `location` to `region_name`:

* **`mapstructure.Decode` returns `nil` error** for an unmatched key. Nothing in `graphquery` or the collector checks `Metadata.Unused` or requires full population.
* The struct field is simply left at its **Go zero value** (`""` or `0`). Decoding an empty row-set and decoding a mis-shaped row-set are indistinguishable downstream.
* `errorCounter` (`exporter_collector_errors_total`) is incremented **only** on transport failure or on `json.Unmarshal` failing inside `parseIPTags`. "We decoded zero usable rows" increments nothing — and in any case **no alert rule in the repo watches `exporter_collector_errors_total`**.
* `Describe()` unconditionally emits `ServiceTagUsageByPublicIpCountDesc`, so the metric *family* is always registered. Prometheus's `absent()` protection never triggers, because absence of *label values* inside an always-present family is invisible — and no `absent()` rule exists for this metric (the only `absent(` uses in the repo are the upstream kubelet/apiserver rules).
* `prometheus.MustNewConstMetric` enforces **arity only** — it panics if the number of label values doesn't match `[]string{...}`. It says nothing about whether the values are semantically right. A rename that preserves arity is completely silent.
* Consequences split by which column drifts: a renamed `ipTagsString` yields `""` → `parseIPTags("")` returns an **empty slice** → the inner `for _, ipTag := range ipTags` never executes → **no series at all**. A renamed `Count` yields `0` → series still published with value **0** → the `/32 > 0.8` alert simply stops firing. Both are silent; neither produces an error, a log line, or a counter tick.

For contrast, the sibling collector `kusto_logs_current.go` shares this architecture but is *not* silent: if a projected column in `tooling/hcpctl/pkg/kusto/templates/builtin/**.kql.gotmpl` drifts from `NormalizedLogLine`'s `kusto:"timestamp"` tag (`tooling/hcpctl/pkg/mustgather/gather.go:80`), `Timestamp` stays zero, `time.Since(zero)` becomes an enormous number, and `kusto_logs_age_in_seconds > 3600` (`observability/alerts/kusto-logs-age-prometheusRule.yaml`) fires loudly. The service-tag chain has no equivalent tripwire — which is exactly what makes its disagreement silent.

## Why a stale value survives for a period once rows stop arriving

Four independent delays stack:

1. **Collection interval (2m).** `collectLoop` refreshes on `--collection-interval` = `2m`; nothing pushes a fresh value between ticks.
2. **Cache TTL (60m, not the code default of 1m).** `values.yaml` sets `cacheTTL: "60m"`. `Cache.Set` stamps `created`, and `GetAll` only removes an entry when `now.Sub(e.created) > c.ttl` — and only when a scrape actually calls `GetAll`. So the moment rows stop arriving, the last written metric object is re-served verbatim to every 30s scrape for **up to 60 minutes**. There is no staleness marker, no `NaN` publication, and no "age of this value" companion metric.
3. **Empty-success is indistinguishable from real success.** If the query returns no rows, the loop body simply doesn't run; the previous cache entries are never overwritten *or* invalidated. Only a transport error increments `errorCounter` — and again, nothing alerts on that counter.
4. **Prometheus lookback-delta (~5m).** Even after the cache entry finally expires and the scrape stops returning the series, Prometheus keeps evaluating the alert expression against the last sample for roughly 5 more minutes.

Combined worst case ≈ collection tick remainder + 60m TTL + ~5m lookback before the alert expression would even begin to resolve — and because the alert is a `> 0.8` threshold rather than an absence check, it doesn't "resolve" into anything visible either; it just quietly goes non-firing.

---

**Summary of the failure surface, with locations:**
- `tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go` — implicit KQL↔struct field-name marriage (no mapstructure/json tags, no `ErrorUnused`, no `Metadata` check), zero-value fallthrough, value-0 fallthrough.
- `tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go` — `mapstructure.Decode` error-only contract.
- `tooling/metricscache/cache.go` — TTL-gated lazy expiry with no staleness signal.
- `tooling/aro-hcp-exporter/deploy/values.yaml` — `cacheTTL: 60m` overriding the 1m default.
- `observability/alerts/service-tag-public-ip-usage.yaml` + `dev-infrastructure/modules/metrics/rules/generatedPrometheusAlertingRules.bicep` — threshold-only alerting, no `absent()`/error-counter guard.

No changes were made; per instructions this is analysis only. If you want a fix designed, the natural candidates are `mapstructure` tags plus `DecoderConfig{ ErrorUnused: true }` (or an explicit row-count/zero-value check) in `service_tag_usage.go`, and either a `count by (...)` / `absent()`-style guard or a cache-age metric so staleness is observable — but I have deliberately implemented none of them.

Read-only investigation complete; no files were modified. Full findings in the preceding message: the `public_ip_count_by_region_service_tag` chain runs from the KQL in tooling/aro-hcp-exporter/internal/metrics/service_tag_usage.go through graphquery's mapstructure.Decode into an untagged PublicIPAddress struct, into metricscache, and out to the threshold alerts in observability/alerts/service-tag-public-ip-usage.yaml. Disagreements are silent because the query-to-struct link is implicit case-insensitive field-name matching with no ErrorUnused/Metadata check, errorCounter only covers transport/JSON failures, MustNewConstMetric checks arity only, and no absent()/error-counter alert exists. Stale values persist up to ~65 minutes because of the 2m collection interval, the 60m cache TTL in values.yaml with lazy scrape-time expiry, the fact that an empty row set never invalidates old cache entries, plus Prometheus's ~5m lookback-delta. Fix options (tags + ErrorUnused, row-count guard, staleness metric) are described but deliberately not applied.