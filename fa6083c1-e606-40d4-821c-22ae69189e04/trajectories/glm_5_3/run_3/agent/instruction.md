<uploaded_files>
/workspace/apache__iotdb__8e5e8502
</uploaded_files>

I've uploaded a code repository in the directory `/workspace/apache__iotdb__8e5e8502`.

## Your Task

We are finishing a dependency inventory for a supply chain review of this database and one routine is the last open item. It sits on the ingestion side and is the one that handles the value columns of an incoming batch. Two earlier attempts to write this up disagreed with each other, so the reviewer wants it settled against the source itself and not from how the tree is laid out. For that routine I need every function defined inside this repository that it calls directly, each paired with the file that declares it and the module that file belongs to, since dependencies are recorded at module granularity. I also need the exclusions written down with a reason attached to each, because the disagreement was entirely about what belonged on the list, and anything the routine reaches only by way of something else it calls is an exclusion as well. The inventory is audited afterwards, so an entry we cannot justify against the source counts against us more heavily than a late one, which means the list has to be complete and no wider than the truth. Read the real source, quote every identifier exactly as it is written there, and give the declaring file for each entry. Change nothing at all.
