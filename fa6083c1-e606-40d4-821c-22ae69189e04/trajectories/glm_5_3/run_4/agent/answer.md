I now have everything I need. Let me consolidate the findings.

The routine: `AlignedWritableMemChunk.writeAlignedTablet` at `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/storageengine/dataregion/memtable/AlignedWritableMemChunk.java:239`.

Its job: handle the value columns of an incoming (aligned) batch on the ingestion side — it reorders the batch's value columns (+ null bitmaps) into the memtable's column order, appends them into the in-memory AlignedTVList, and sorts when the threshold is reached.

Direct callees (verified against source):
1. `checkAndReorderColumnValuesInInsertPlan` — same file, line 265 (private). Inside it calls:
   - `this.measurementIndexMap.get(...)` / `.put(...)` — `Map<String, Integer>` field, line 68 (LinkedHashMap, initialized at line 92)
   - `this.list.getTsDataTypes()` — AlignedTVList.java:641-643, returns `dataTypes` (field declared at line 82)
   - `this.list.extendColumn(TSDataType)` — AlignedTVList.java:391
   - `Arrays.copyOf` — `java.util.Arrays`
   - `new Pair<>(reorderedColumnValues, reorderedBitMaps)` — `org.apache.tsfile.utils.Pair` (external tsfile dependency 2.3.2-260616-SNAPSHOT)
2. `putAlignedTablet` — same file, line 201. Calls:
   - `list.putAlignedValues(t, v, bitMaps, start, end, results)` — AlignedTVList.java:881 (synchronized). Inside `putAlignedValues`:
     - `checkExpansion()` — TVList.java:654 → `expandValues()`, `getPrimitiveArraysByType`, `PrimitiveArrayManager.allocate`
     - `updateMinMaxTimeAndSorted(time, start, end)` — TVList.java:671
     - `System.arraycopy`
     - `markNullBitmapRange(...)` — AlignedTVList.java:923 → `containsFailedStatus` (957), `buildResultBitMapBytes` (991), `containsMarkedBit` (966), `getBitMap(j, arrayIndex).markRange/merge` (1059), `markNullValue(j, arrayIndex, elementIdx, resultBitMap)` (1086) → `markNullValue(int,int,int)` (1095) → `BitMap.isMarked/mark`
     - `arrayCopy(value, idx, arrayIdx, elementIdx, internalRemaining)` — AlignedTVList.java:1011, switch on `dataTypes.get(i)` (TEXT/BLOB/STRING/OBJECT → Binary[], FLOAT → float[], INT32/DATE → int[], INT64/TIMESTAMP → long[], DOUBLE → double[], BOOLEAN → boolean[]), uses `getBinarySize` from `MemUtils` (MemUtils.java:115)
3. `list.rowCount()` — TVList.java:237
4. `handoverAlignedTvList()` — same file, line 217 → `list.sort()`, `sortedList.add(list)`, `sortedRowCount`

Fields read directly: `list` (line 72, AlignedTVList created via `AlignedTVList.newAlignedList(dataTypes)` line 99 — factory at AlignedTVList.java:116, dispatches to QuickAlignedTVList / BackAlignedTVList etc.), `TVLIST_SORT_THRESHOLD` (line 78, `CONFIG.getTvListSortThreshold()`), `sortedList` (line 73).

Call path leading in (context, for justification that this is the ingestion-side value-column handler):
- `ClientRPCServiceImpl.insertTablet` (ClientRPCServiceImpl.java:2728) → ... → `DataRegion.insertTablet` (DataRegion.java:1419) → `TsFileProcessor.insertTablet` (TsFileProcessor.java:591) → `AbstractMemTable.insertTablet` (279) / `insertAlignedTablet` (300) → `writeTabletNode` (374) / `writeAlignedTablet` (409) → `IWritableMemChunkGroup.writeTablet` (IWritableMemChunkGroup.java:39) → `AlignedWritableMemChunkGroup.writeTablet` (AlignedWritableMemChunkGroup.java:64) → `AlignedWritableMemChunk.writeAlignedTablet` (239).

Exclusions (things NOT direct entries of this routine, though they showed up in the "valueColumn" grep):
- `WritableMemChunkGroup.writeTablet` (WritableMemChunkGroup.java:60-74) → `WritableMemChunk.writeNonAlignedTablet` (WritableMemChunk.java:144) → `putBooleans/putInts/putLongs/putFloats/putDoubles/putBinaries` (WritableMemChunk.java:232-259) → `list.putLongs/...` — this is the non-aligned sibling path; reachable from `AbstractMemTable.insertTablet` but NOT from `writeAlignedTablet`. Excluded from the aligned routine's direct inventory.
- `AlignedWritableMemChunk.writeAlignedPoints` (228) / `putAlignedRow` (166) — row ingestion path, not the batch path.
- `AlignedWritableMemChunk.writeNonAlignedTablet` (212) / `writeNonAlignedPoint` (207) — throw `UnSupportedDataTypeException`, unreachable in practice for aligned chunks.
- All compaction-side `valueColumn` code (FastAlignedSeriesCompactionExecutor etc.), query-side (`IoTDBRpcDataSet`, `SessionDataSet`, REST `QueryDataSetHandler`), calc/UDF (`UDTFExecutor`, `PointCollectorAdaptor`, `TableOperatorGenerator`) — different subsystems, not ingestion.
- tsfile external types: `BitMap`, `Pair`, `Binary`, `IMeasurementSchema`, `EncryptParameter`, `EncryptUtils`, `TSDataType` — external artifact `org.apache.tsfile:tsfile:2.3.2-260616-SNAPSHOT`, not present in this repo, so their internals cannot be verified against this source tree; note as external dependency entries, not auditable here.

Also `TSStatus` (org.apache.iotdb.common.rpc.thrift.TSStatus — thrift generated), `TSStatusCode` (org.apache.iotdb.rpc.TSStatusCode — enum at iotdb-client/service-rpc/.../TSStatusCode.java:32).

Now, "ONE ONLY ONE FUNCTION CALL PER MESSAGE" — I must respect: only one function call per message. I've been doing that. Now I should write the final answer as prose (message), then call finish.

Actually — I must first send the answer to the user through a message, then finish. But the interface: I write the final message as part of the `finish` tool call, or I send a plain message then finish? Instructions say: "please first send your answer to user through message and then finish the interaction." A plain assistant message (no function call) would end my turn without the finish tool. Hmm. But the finish tool itself carries a message. The safest: send the full answer as a plain text message... but then the interaction may end without finish. Actually I can send a message and then in the next turn call finish. But there's no next turn unless user replies. The harness prompt says "If you think you have solved the task, please first send your answer to user through message and then finish the interaction." — meaning within one assistant message I cannot do both (one function call per message, and text+function call is allowed: "You may provide optional reasoning for your function call in natural language BEFORE the function call"). So I can put the full answer as the text and then call finish. That satisfies both.

Let me write the final deliverable: the routine + direct inventory with file:line, quoted identifiers, exclusions with reasons. Note the ambiguity: "value columns of incoming batch" — the aligned path is the one where plural value columns are handled as a set (Object[] valueList); the non-aligned path handles one column per memchunk. Both are defensible; I'll present writeAlignedTablet as the routine that handles the value columns (plural) of the incoming batch, and record the non-aligned path as an explicit exclusion with justification, since a reviewer needs to know why. That's honest and complete.
I have settled the last open item against source. Here is the inventory entry.

## Subject routine (settled against source)

**`AlignedWritableMemChunk.writeAlignedTablet`**
`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/storageengine/dataregion/memtable/AlignedWritableMemChunk.java:239`
Signature (quoted): `public void writeAlignedTablet(long[] times, Object[] valueList, BitMap[] bitMaps, List<IMeasurementSchema> schemaList, int start, int end, TSStatus[] results)`

This is the ingestion-side routine that handles the value columns of an incoming batch: it takes the batch's value columns (`Object[] valueList`) plus their null bitmaps (`BitMap[] bitMaps`), reorders them into the memtable's column order, appends them to the in-memory aligned list, and sorts on threshold. Inbound chain that reaches it: `ClientRPCServiceImpl.insertTablet` (`ClientRPCServiceImpl.java:2728`) â `DataRegion.insertTablet` (`DataRegion.java:1419`) â `TsFileProcessor.insertTablet` (`TsFileProcessor.java:591`) â `AbstractMemTable.insertAlignedTablet` (`AbstractMemTable.java:300`) â `writeAlignedTablet` (`AbstractMemTable.java:409`) â `AlignedWritableMemChunkGroup.writeTablet` (`AlignedWritableMemChunkGroup.java:64`) â this routine.

## Direct entries (what the routine reaches directly â function granularity, quoted identifiers)

In `AlignedWritableMemChunk.java` (same file unless noted):
- `checkAndReorderColumnValuesInInsertPlan` :265 â private, `Pair<Object[], BitMap[]> checkAndReorderColumnValuesInInsertPlan(List<IMeasurementSchema> schemaListInInsertPlan, Object[] columnValues, BitMap[] bitMaps)`. Its own direct touches: `measurementIndexMap.get(...)/.put(...)` (field :68, `LinkedHashMap` init :92), `list.getTsDataTypes()` (`AlignedTVList.java:641`, returns `dataTypes` :82), `list.extendColumn(TSDataType)` (`AlignedTVList.java:391`), `Arrays.copyOf` (`java.util.Arrays`), `new Pair<>(...)` (`org.apache.tsfile.utils.Pair`).
- `putAlignedTablet` :201 â `public void putAlignedTablet(long[] t, Object[] v, BitMap[] bitMaps, int start, int end, TSStatus[] results)`; body: `list.putAlignedValues(t, v, bitMaps, start, end, results)`.
  - `AlignedTVList.putAlignedValues` â `iotdb-core/datanode/.../utils/datastructure/AlignedTVList.java:881`, `public synchronized void putAlignedValues(long[] time, Object[] value, BitMap[] bitMaps, int start, int end, TSStatus[] results)`. Its direct touches: `checkExpansion()` (`TVList.java:654`), `updateMinMaxTimeAndSorted(time, start, end)` (`TVList.java:671`), `System.arraycopy`, `markNullBitmapRange(...)` (`AlignedTVList.java:923`), `arrayCopy(...)` (`AlignedTVList.java:1011`).
    - `markNullBitmapRange` :923 â `containsFailedStatus` :957, `buildResultBitMapBytes` :991, `containsMarkedBit` :966, `getBitMap(j, arrayIndex)` :1059 then `BitMap.markRange`/`BitMap.merge`, `markNullValue(j, arrayIndex, elementIdx, resultBitMap)` :1086 â `markNullValue(int, int, int)` :1095 â `BitMap.isMarked`/`BitMap.mark`.
    - `arrayCopy` :1011 â switches on `dataTypes.get(i)`: `TEXT/BLOB/STRING/OBJECT â Binary[]`, `FLOAT â float[]`, `INT32/DATE â int[]`, `INT64/TIMESTAMP â long[]`, `DOUBLE â double[]`, `BOOLEAN â boolean[]`; uses `getBinarySize` (`MemUtils.java:115`).
- `list.rowCount()` â `TVList.java:237`.
- `handoverAlignedTvList()` :217 â body: `list.sort()`, `sortedList.add(list)`, `sortedRowCount` update; gated by `TVLIST_SORT_THRESHOLD > 0 && list.rowCount() >= TVLIST_SORT_THRESHOLD` (field :78 = `CONFIG.getTvListSortThreshold()`).
- Fields on the routine itself: `list` (:72, built by `AlignedTVList.newAlignedList(dataTypes)` :99, factory `AlignedTVList.java:116` dispatching `QuickAlignedTVList`/`BackAlignedTVList`), `sortedList` (:73), `schemaList` (:70), `measurementIndexMap` (:68), `dataTypes` (:69), `encryptParameter` (:82).

## Exclusions (anything else the greps surface is excluded; reasons quoted from source)

- `WritableMemChunkGroup.writeTablet` (`WritableMemChunkGroup.java:60`) â `WritableMemChunk.writeNonAlignedTablet` (`WritableMemChunk.java:144`) â `putBooleans/putInts/putLongs/putFloats/putDoubles/putBinaries` (`WritableMemChunk.java:232â259`) â `list.putLongs/...`: the **non-aligned** sibling, reached from `AbstractMemTable.insertTablet`/`writeTabletNode` (:279/:374), not from `writeAlignedTablet`. Excluded as a different routine's entry.
- `AlignedWritableMemChunk.writeAlignedPoints` :228 / `putAlignedRow` :166: row-by-row ingestion (`writeAlignedRow` path), not batch. Excluded.
- `AlignedWritableMemChunk.writeNonAlignedTablet` :212 and `writeNonAlignedPoint` :207: bodies are `throw new UnSupportedDataTypeException(UNSUPPORTED_TYPE + TSDataType.VECTOR)` â unreachable for an aligned chunk. Excluded.
- All compaction-side identifiers (`FastAlignedSeriesCompactionExecutor` value-column code, `ReadChunkAlignedSeriesCompactionExecutor.collectValueColumnSchemaListForTable/ForTree`, `BatchedFastAlignedSeriesCompactionExecutor.getAlignedChunkMetadataListBySelectedValueColumn`), query-side (`IoTDBRpcDataSet`, `SessionDataSet`, REST `QueryDataSetHandler`), and calc/UDF (`UDTFExecutor`, `PointCollectorAdaptor`, `TableOperatorGenerator` `valueColumnIndex`): different subsystems, no call edge from this routine. Excluded.
- External artifact types â `BitMap`, `Pair`, `Binary`, `IMeasurementSchema`, `TSDataType`, `EncryptParameter`/`EncryptUtils` â resolve to `org.apache.tsfile:tsfile:2.3.2-260616-SNAPSHOT` (pom.xml:148), which is **not present in this checkout**; their internals cannot be verified against this source tree and are recorded as external dependency references, not audited entries. `TSStatus`/`TSStatusCode` resolve to thrift-generated/RPC code (`org.apache.iotdb.rpc.TSStatusCode`, `iotdb-client/service-rpc/.../TSStatusCode.java:32`) and are used only as status codes here.

Note on the earlier disagreement: the ambiguity comes from two sibling paths (aligned `writeAlignedTablet` vs non-aligned `writeTablet`/`writeNonAlignedTablet`). Source settles it: only `writeAlignedTablet` takes the batch's value *columns* as a set (`Object[] valueList` + `BitMap[] bitMaps`), which matches the item description; the non-aligned path handles one column per `WritableMemChunk` and is listed above as an exclusion with its reason.

Settled the last inventory item against source. The ingestion-side routine handling the value columns of an incoming batch is `AlignedWritableMemChunk.writeAlignedTablet` (iotdb-core/datanode/src/main/java/org/apache/iotdb/db/storageengine/dataregion/memtable/AlignedWritableMemChunk.java:239). Direct entries: `checkAndReorderColumnValuesInInsertPlan` (:265), `putAlignedTablet` (:201) â `AlignedTVList.putAlignedValues` (AlignedTVList.java:881, with `checkExpansion`/`updateMinMaxTimeAndSorted`/`markNullBitmapRange`/`arrayCopy` and their leaf helpers), `list.rowCount()` (TVList.java:237), and `handoverAlignedTvList()` (:217); each entry was quoted with identifier and file:line. Exclusions were recorded with reasons: the non-aligned path (`WritableMemChunkGroup.writeTablet` â `WritableMemChunk.writeNonAlignedTablet`), the row path (`writeAlignedPoints`/`putAlignedRow`), unreachable throws (`writeNonAlignedTablet`/`writeNonAlignedPoint`), all compaction/query/calc "valueColumn" identifiers, and external `org.apache.tsfile` types (tsfile 2.3.2-260616-SNAPSHOT, not in this checkout) which cannot be audited against this tree.