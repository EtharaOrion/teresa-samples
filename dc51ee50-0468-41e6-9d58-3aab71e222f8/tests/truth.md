# Ground truth - dc51ee50-0468-41e6-9d58-3aab71e222f8

- **repo:** `Azure/ARO-HCP`
- **base_commit:** `7cfa67722f96feb45f75681e10abfd11ae4b294a`
- **family:** dependency_search
- **source PR:** #6135, closed and merged as `ff8ebf12ed24e65c88017855f60ef9e12bb71326`
  (`base_commit` is `merge^1`, so the tree described here is the pre-refactor code).

## Summary

The exported gauge is bound to the text of a query by nothing but **Go field names**. The hinge
is `ExecuteConvertRequest` in `tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go` (line 50),
which hands the untyped query result to `mapstructure.Decode` at line 62. The destination struct
carries no field tags, so each projected column is matched to a field by name alone. Renaming a
projected column therefore leaves the matching field at its zero value, `Decode` still returns
nil, and the row silently produces no metric at all. The staleness that hides it comes from a
third package: the metric cache keeps serving the previous value until its TTL elapses.

## The dependency chain at `base_commit`

### 1. The producer - the query text in `internal/metrics/service_tag_usage.go`

Lines 109-114 hold the query as a package-level string:

```go
var query = `
resources
| where type == 'microsoft.network/publicipaddresses'
| extend ipTagsString = tostring(properties['ipTags'])
| summarize Count=count()  by  subscriptionId, location, ipTagsString
`
```

The `summarize ... by` clause is what fixes the output column names: `subscriptionId`,
`location`, `ipTagsString` and `Count`.

### 2. The consumer - the destination struct in the same file

Lines 102-107 declare the shape the result is decoded into:

```go
type PublicIPAddress struct {
	Location       string
	IpTagsString   string
	SubscriptionId string
	Count          float64
}
```

There is **no struct tag of any kind** on these four fields. That is the whole contract. The
only thing tying `ipTagsString` in the query to `IpTagsString` in Go is that the two spellings
agree once case is folded.

`CollectMetricValues` at line 129 joins the two halves, passing the query and the destination
together at lines 135-138:

```go
err = c.client.ExecuteConvertRequest(ctx, graphquery.ResourceGraphRequest{
	Query:  &query,
	Output: &publicIPs,
})
```

### 3. The hinge - `ExecuteConvertRequest` in `pkg/graphquery/public_ips.go` (the gold)

The request type at lines 36-39 is deliberately opaque: `Query *string` and `Output any`. The
compiler therefore checks nothing about the pairing. `ExecuteConvertRequest` at line 50 runs the
query, scoped to the client's stored `subscriptionIDs` at line 54, and then performs the bind at
line 62:

```go
err = mapstructure.Decode(result.Data, &request.Output)
if err != nil {
	return fmt.Errorf("failed to decode Resource Graph result: %w", err)
}
```

`result.Data` arrives from the SDK as an untyped value. With no tags on the destination fields,
`mapstructure` matches keys to field names case-insensitively; keys that match no field are
ignored, and fields that match no key are left at their zero value. Neither situation is an
error, so `Decode` returns nil and the wrapping at line 64 never triggers.

This single line is the coupling. Every column name in section 1 and every field name in
section 2 must agree here, and nothing in the type system, the compiler or the runtime enforces
that agreement.

### 4. What a rename actually does downstream

Back in `service_tag_usage.go`, the error handling at lines 139-143 is the only guard, and it
fires solely on a returned error:

```go
if err != nil {
	c.errorCounter.Inc()
	logger.Error(err, "error collecting public IP addresses")
	return
}
```

Because the decode succeeded, `errorCounter` stays flat and nothing is logged.

The consequence then depends on which field went zero. If `IpTagsString` is the empty string,
line 147 tests `publicIP.IpTagsString != "[]"`, which is true for `""`, so `parseIPTags("")` is
called. Its first branch, lines 119-121, returns an empty slice and a nil error:

```go
if ipTagsAsString == "" {
	return ipTags, nil
}
```

The range at line 162 then iterates zero times, so `c.cache.Set` at line 164 is never reached
and **the row contributes no series whatsoever**. A rename of `subscriptionId` or `location`
instead yields a series carrying an empty label value, and a rename of `Count` yields a gauge
reporting zero.

### 5. Why the same file proves the fragility is a choice

Lines 97-100 declare the other decoded type in this file with explicit tags:

```go
type IPTag struct {
	ServiceTagType  string `json:"ipTagType"`
	ServiceTagValue string `json:"tag"`
}
```

`parseIPTags` decodes it with `encoding/json` at line 122. So one file holds two decoders and
two conventions: the nested payload is bound by declared tags, while the outer query result is
bound by bare field names. The tagged half survives a rename of the Go field; the untagged half
does not.

### 6. Why the breakage persists - `tooling/metricscache/cache.go`

The collector never writes to Prometheus directly. `Collect` at lines 91-95 serves
`c.cache.GetAll()`, and `Set` at line 164 is the only writer. In `tooling/metricscache/cache.go`,
`Set` at line 52 stamps each entry with the current time, and `GetAll` at line 59 drops an entry
only once `now.Sub(e.created) >= c.ttl`.

Nothing marks an entry as absent. When a collection cycle stops producing a row, the previously
cached series continues to be served on every scrape until its TTL elapses, so the gauge holds
its last good value and then vanishes with no event in between.

`internal/cmd/serve.go` closes the loop: `collectLoop` at line 130 calls
`collector.CollectMetricValues(ctx)` at line 141 on a fixed interval, so the silent failure
simply repeats every cycle.

### 7. What else shares the fragility, and what does not

`KustoLogsCurrentCollector` in `internal/metrics/kusto_logs_current.go` shares the same cache
(field at line 51, constructed at line 75, served at line 89), so it inherits the same staleness
behavior. It reaches its data through a Kusto query client instead, so it is untouched by the
name-based binding. The untagged binding is therefore specific to the path that runs through
`ExecuteConvertRequest`, while the staleness is common to every collector holding a cache.

## Adjacent surfaces the solver can see (none disclose the gold)

- `tooling/aro-hcp-exporter/` has **no** docs directory of its own, which is why this corner was
  chosen: `kube-applier/docs/` and `docs/` elsewhere in the repository name internals with file
  and line numbers, and `sanitize: true` would not remove them.
- `tooling/aro-hcp-exporter/internal/cluster/cluster_discovery_poller.go` and its test do **not**
  exist at `base_commit`; both are added by the source PR.

## What the merged PR changed (the after state)

PR #6135 renamed `pkg/graphquery/public_ips.go` to `pkg/graphquery/query_client.go`, introduced
`internal/cluster/cluster_discovery_poller.go` so cluster discovery runs through a shared Resource
Graph poller keyed on a `clusterType` tag, and reworked `internal/cmd/options.go` and
`internal/metrics/service_tag_usage.go` around it. The after state is recorded for the boundary
only; the gold localizes the dependency chain as it stands at `base_commit`.

```json <!-- gold -->
{
  "file": "tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go",
  "function": "ExecuteConvertRequest",
  "explanation": "ExecuteConvertRequest at tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go line 50 is the hinge that binds the query text to the exported series. It runs the query scoped to the client's subscriptionIDs at line 54 and then calls mapstructure.Decode(result.Data, &request.Output) at line 62. The request type at lines 36 to 39 carries Query as a *string and Output as any, so the compiler checks nothing about the pairing. The producing half is the query string at internal/metrics/service_tag_usage.go lines 109 to 114, whose summarize by clause fixes the column names subscriptionId, location, ipTagsString and Count. The consuming half is PublicIPAddress at lines 102 to 107, whose four fields carry no struct tag at all, so mapstructure matches columns to Go field names case-insensitively, ignores keys matching no field and leaves fields matching no key at their zero value. None of that is an error, so Decode returns nil, the guard at lines 139 to 143 never fires, errorCounter stays flat and nothing is logged. If IpTagsString goes empty the test at line 147 passes it to parseIPTags, whose empty-string branch at lines 119 to 121 returns an empty slice and a nil error, so the range at line 162 never reaches c.cache.Set at line 164 and the row emits no series. The same file proves this is a choice, since IPTag at lines 97 to 100 declares json tags ipTagType and tag and is decoded by encoding/json at line 122. The breakage persists because Collect at lines 91 to 95 serves tooling/metricscache/cache.go, where Set at line 52 stamps entries and GetAll at line 59 drops one only once its TTL has elapsed, so the last good value keeps being scraped; internal/cmd/serve.go drives the repeat through collectLoop at line 130 calling CollectMetricValues at line 141."
}
```
