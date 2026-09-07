The user keeps asking me to continue. Let me just deliver the final complete answer now, then call finish.
## Settled: the ingestion-side routine handling value columns of an incoming batch

**`public Pair<Object[], ByteBuffer> decodeValues(ByteBuffer buffer)`**
Location: `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/TabletDecoder.java:124` (module `iotdb-server`, "IoTDB: Core: Data-Node (Server)")

### Why this settles the disagreement
Two routines decode tablet value columns; the disagreement came from conflating them. Source shows they serve **different ingestion entry points**:

| Path | Entry | Value-column routine | Evidence |
|---|---|---|---|
| Batch (multi-tablet) | `insertTablets(TSInsertTabletsReq)` → `StatementGenerator.createStatement(TSInsertTabletsReq)` | `QueryDataSetUtils.readTabletValuesFromBuffer(...)` | `StatementGenerator.java:412` |
| **Batch tablet (single)** | `insertTablet(TSInsertTabletReq)` → `StatementGenerator.createStatement(TSInsertTabletReq)` | **`TabletDecoder.decodeValues`** | `ClientRPCServiceImpl.java:2728`; `StatementGenerator.java:332, 348, 363` |

`InsertTabletNode.java:860,1279` also calls `readTabletValuesFromBuffer`, but only during **deserialization** (internal plan-node transfer), not client batch ingestion. `decodeValues` is the only one that decompresses a client-sent encoded/compressed value payload (`TSInsertTabletReq.values`).

### Entries — reached directly by `decodeValues`
- `RPCServiceThriftHandlerMetrics.getInstance()` — `RPCServiceThriftHandlerMetrics.java:173`, class `:33`
- `.recordUnCompressionSizeTimer(long)` — `:51` (field `unCompressionSizeTimer` `:39`)
- `.recordCompressionSizeTimer(long)` — `:55` (field `compressionSizeTimer` `:40`)
- `.recordDecodeLatencyTimer(long)` — `:59` (field `decodeLatencyTimer` `:41`)
- `uncompress(ByteBuffer)` — `TabletDecoder.java:86`
- `decodeColumn(ByteBuffer, int)` — `TabletDecoder.java:142`
- `new Pair<>(columns, uncompressed)` — `:139`; type `org.apache.tsfile.utils.Pair` (external tsfile)
- `System.nanoTime()` — JDK
- Fields: `dataTypes` `:42`, `compressionType` `:41`, `unCompressor` `:44`, `columnEncodings` `:43`, `rowSize` `:45`

### Exclusions — reached only transitively (via `uncompress`/`decodeColumn`), not by `decodeValues`
- `CompressionType.UNCOMPRESSED`, `IUnCompressor.uncompress(...)`, `ByteBuffer.getInt/wrap`, `new byte[...]` (`:88–100`)
- `IoTDBRuntimeException` (`iotdb-core/node-commons/.../exception/IoTDBRuntimeException.java`), `DataNodeMiscMessages.MISC_EXCEPTION_FAILED_TO_DECOMPRESS_COMPRESSEDBUFFER_56398D3E` (`DataNodeMiscMessages.java:1347`), `TSStatusCode.INTERNAL_SERVER_ERROR.getStatusCode()` (`iotdb-client/service-rpc/.../TSStatusCode.java:51`), `.recordDecompressLatencyTimer` (`:63`), `.recordMemoryUsage` (`:67`)
- `Decoder.getDecoderByType(encoding, dataType)`, `Decoder.readInt/readLong/readFloat/readDouble/readBoolean/readBinary`, `TSEncoding.PLAIN`, `ReadWriteIOUtils.readInt/readBinary` (`:146,152,155,159,168,175,183,189,200,204`), `DataNodeMiscMessages.UNSUPPORTED_DATA_TYPE` (`DataNodeMiscMessages.java:635`), `TSDataType`/`Binary` types and enum constants (`DATE, INT32, INT64, TIMESTAMP, FLOAT, DOUBLE, BOOLEAN, STRING, BLOB, TEXT, UNKNOWN, VECTOR`)

No entry remains unaudited; the classifier ("direct" vs "transitive/excluded") is stated for every identifier above.

Dependency inventory item settled against source. The ingestion-side routine handling value columns of an incoming client batch is TabletDecoder.decodeValues (TabletDecoder.java:124), invoked from StatementGenerator.createStatement(TSInsertTabletReq) at line 363 on the insertTablet RPC path (ClientRPCServiceImpl.java:2728). The earlier disagreement is explained: QueryDataSetUtils.readTabletValuesFromBuffer (StatementGenerator.java:412) serves the multi-tablet insertTablets path and internal InsertTabletNode deserialization (InsertTabletNode.java:860,1279), and does not decompress client payloads. Every identifier reached by decodeValues is classified as a direct entry or a transitive exclusion with file:line quotes; no unaudited entries remain.