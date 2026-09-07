<uploaded_files>
/workspace/Azure__ARO-HCP__7cfa6772
</uploaded_files>

I've uploaded a code repository in the directory `/workspace/Azure__ARO-HCP__7cfa6772`.

## Your Task

We are about to rename one of the fields projected by the text of a query that backs one of our published Prometheus gauges, and I want to know precisely what that will break before anybody merges it. My nervousness comes from a very similar change a while back that went badly in an unusually quiet way. The affected series simply stopped appearing. Nothing showed up in the logs, the counter we keep for collection failures sat at zero the whole time, and for a good while after collection had already stopped yielding rows the previous numbers were still being handed to every scrape, so the graphs looked perfectly healthy long after they had stopped meaning anything. Nobody spotted it for most of a day. What I need from you is the real dependency chain, traced in the actual code, that ties the text of that query to the labels and the value on the series we publish. Tell me where the two ends are genuinely married up, what makes a disagreement between them completely silent instead of loud, and why a stale value survives for a period once the rows stop arriving. Please go and read the real source with care, follow the chain through every file that it passes through, and change nothing at all, this is strictly a read only investigation.
