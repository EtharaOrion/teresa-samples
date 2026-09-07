# Dependency inventory — final entry

**No files were created, modified, deleted, or annotated. My diff is empty.** Everything below is recorded here, not in the repo.

---

## 1. Settling which routine this is

"Ingestion side, handles the value columns of an incoming batch" maps to **two** distinct routines in `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/`, and that ambiguity is the most likely cause of the two earlier attempts disagreeing:

| Candidate | Location | Reached from |
|---|---|---|
| **A.** `QueryDataSetUtils.readTabletValuesFromBuffer(ByteBuffer, TSDataType[], int, int)` | `QueryDataSetUtils.java:622-687` | `StatementGenerator.createStatement(TSInsertTabletsReq)` at `StatementGenerator.java:411-416` (via the `List<Integer>` overload, `QueryDataSetUtils.java:603-611`); `InsertTabletNode.java:860` and `:1279` |
| **B.** `TabletDecoder.decodeValues(ByteBuffer)` | `TabletDecoder.java:124-140` | `StatementGenerator.java:363` (single-tablet `TSInsertTabletReq`, compressed/encoded path) |

I audited **A**. Reasons, from the source: it is the reader named for the value columns (`readTabletValues…`), it is the one the multi-tablet ingest path and both `InsertTabletNode` deserialization paths call, and it is a pure decode of raw column payload. **B** is a different shape of work — it decompresses (`uncompress`, `TabletDecoder.java:86-110`) and runs per-column `Decoder`s (`TabletDecoder.java:146`), pulling in `IUnCompressor`, `Decoder`, `TSEncoding`, `CompressionType`, `ReadWriteIOUtils` and `Pair`, none of which A touches. If the reviewer meant **B**, the inventory below does not cover it and must be redone; I flag that explicitly rather than silently merging the two.

There is also a sibling reader, `readTabletValuesFromStream` (`QueryDataSetUtils.java:689-724` plus helpers `parseBooleanColumn`…`parseTextColumn`, `:726-783`). It is the stream twin of A, reached only from `InsertTabletNode.java:1238`. It is **not** part of this entry — I state that so the boundary is unambiguous.

Granularity, as requested: **type level**, direct references from the routine body only (no transitive closure into third-party internals).

---

## 2. Identifiers reached, quoted from source

Every identifier appearing in `QueryDataSetUtils.java:622-687` (plus the thin overload `:603-611` that delegates into it):

```
622|   @SuppressWarnings("squid:S3776")
623|   public static Object[] readTabletValuesFromBuffer(
624|       ByteBuffer buffer, TSDataType[] types, int columns, int size) {
625|     Object[] values = new Object[columns];
626|     for (int i = 0; i < columns; i++) {
627|       switch (types[i]) {
628|         case BOOLEAN:
629|           boolean[] boolValues = new boolean[size];
631|             boolValues[index] = BytesUtils.byteToBool(buffer.get());
633|           values[i] = boolValues;
635|         case INT32:
636|         case DATE:
637|           int[] intValues = new int[size];
639|             intValues[index] = buffer.getInt();
643|         case INT64:
644|         case TIMESTAMP:
645|           long[] longValues = new long[size];
647|             longValues[index] = buffer.getLong();
651|         case FLOAT:
652|           float[] floatValues = new float[size];
654|             floatValues[index] = buffer.getFloat();
658|         case DOUBLE:
659|           double[] doubleValues = new double[size];
661|             doubleValues[index] = buffer.getDouble();
665|         case TEXT:
666|         case BLOB:
667|         case STRING:
668|         case OBJECT:
669|           Binary[] binaryValues = new Binary[size];
671|             int binarySize = buffer.getInt();
672|             byte[] binaryValue = new byte[binarySize];
673|             buffer.get(binaryValue);
674|             binaryValues[index] = new Binary(binaryValue);
679|           throw new UnSupportedDataTypeException(
680|               String.format(
681|                   DataNodeMiscMessages
682|                       .MISC_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC,
683|                   types[i]));
686|     return values;
```

and from the overload:

```
604|   public static Object[] readTabletValuesFromBuffer(
605|       ByteBuffer buffer, List<Integer> types, int columns, int size) {
606|     TSDataType[] dataTypes = new TSDataType[types.size()];
608|       dataTypes[i] = TSDataType.values()[types.get(i)];
610|     return readTabletValuesFromBuffer(buffer, dataTypes, columns, size);
```

---

## 3. Inventory entries — audited against `dependencies.json`

`dependencies.json` is the reference list for the SBOM diff (`src/main/groovy/checkDependencies.groovy`, activated by profile `enable-sbom-check`, `pom.xml:1641-1706`). It holds 158 GAV pairs, of which the only tsfile ones are `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`.

| Identifier | Import in file | Candidate entry | Verdict |
|---|---|---|---|
| `org.apache.tsfile.utils.Binary` (`669`, `674`) | line 32 | `org.apache.tsfile:common` **or** `org.apache.tsfile:tsfile` | **INCLUDED — artifact undetermined (see §5)** |
| `org.apache.tsfile.enums.TSDataType` (`624`, `627`, `683`; `606`, `608`) | line 30 | same pair | **INCLUDED — artifact undetermined** |
| `org.apache.tsfile.utils.BytesUtils` (`631`) | line 34 | same pair | **INCLUDED — artifact undetermined** |
| `org.apache.tsfile.write.UnSupportedDataTypeException` (`679`) | line 37 | same pair | **INCLUDED — artifact undetermined** |

Both candidate artifacts are already present in `dependencies.json`, and `iotdb-core/datanode/pom.xml:51-60` declares **both** `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`. So at the level the inventory is consumed (is this dependency justified and listed?), all four rows are justified and complete regardless of which of the two artifacts actually ships each class.

---

## 4. Exclusions — every one written down, with its justification

1. **`java.nio.ByteBuffer`** (`624`, `631`, `639`, `647`, `654`, `661`, `671`, `673`) — JDK. Not an SBOM component; the XSLT (`src/main/xslt/sbom-filter.xsl`) emits only CycloneDX `component` entries, and the JDK is not one. No `dependencies.json` entry can exist. Excluded, justified.
2. **`java.lang.String`** (`680`, `String.format`), **`java.lang.Object`** (`625`), **`java.lang.SuppressWarnings`** (`622`) — JDK, same reasoning. Excluded, justified.
3. **`java.util.List`** (`605`, in the delegating overload) — JDK. Excluded, justified. I counted the overload because it is the entry point `StatementGenerator.java:412` actually calls; its only non-JDK identifier is `TSDataType`, already inventoried.
4. **`org.apache.iotdb.db.i18n.DataNodeMiscMessages`** (`681-682`, import line 23) — first-party. It lives inside this same module at `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodeMiscMessages.java:1343` (zh twin at `:1325`), added as a source root by `build-helper-maven-plugin` in `iotdb-core/datanode/pom.xml:447-463`. `sbom-filter.xsl` filters on `sbom:group!='org.apache.iotdb'`, and I confirmed the parsed `dependencies.json` contains **zero** `org.apache.iotdb:*` entries. Not an inventory candidate at all. Excluded, justified.
5. **Siblings in the same file that this routine does NOT reach** — `BitMap` (used by `readBitMapsFromBuffer`, `:573-601`), `Column`, `TsBlock`, `Pair`, `PublicBAOS`, `TSFileConfig`, `TSFileDescriptor`, `IoTDBException`, `TSQueryDataSet`, `IQueryExecution`, `DataInputStream`, `DataOutputStream`, `IOException`, `ArrayList`, `Optional`. All imported by `QueryDataSetUtils.java` but none appear between lines 603-687. Excluded as out-of-scope for this routine, justified by line-range inspection.
6. **`TabletDecoder`'s dependency set** — `IUnCompressor`, `Decoder`, `TSEncoding`, `CompressionType`, `ReadWriteIOUtils`, `Pair`, `IoTDBRuntimeException`, `TSStatusCode`, `RPCServiceThriftHandlerMetrics`. Excluded because candidate **B** is not the routine audited. If the reviewer intended B, this exclusion is the one to revisit first.

---

## 5. The one thing I could **not** settle against source, stated plainly

`org.apache.tsfile` ships as two artifacts, `common` and `tsfile` (`pom.xml:148` pins `tsfile.version` to `2.3.2-260616-SNAPSHOT`; `pom.xml:316-327` manages `tsfile`). **Which of the two contains `Binary`, `TSDataType`, `BytesUtils` and `UnSupportedDataTypeException` cannot be determined from this checkout**, because:

* no local artifact exists — `~/.m2` is absent and a filesystem-wide search finds no `*.jar` for tsfile;
* the classes are not vendored in-tree (no `org/apache/tsfile` source directory under any module);
* the network is unreachable — `curl` to `repo1.maven.org` returns exit code 6 (DNS resolution failure).

What the poms let me infer, and it is only an inference: the modules that declare **`common` but not `tsfile`** are `iotdb-api/udf-api`, `library-udf` and `example/pipe-count-point-processor`. Their combined tsfile imports are exactly `block.column.Column`, `block.column.ColumnBuilder`, `enums.TSDataType`, `utils.Binary`, `utils.BitMap`, `write.record.Tablet`, `write.schema.MeasurementSchema`. That places **`TSDataType` and `Binary` in `org.apache.tsfile:common`** if those modules compile. No common-only module imports `BytesUtils` or `UnSupportedDataTypeException`, so those two remain unattributed; the only modules importing them all declare both artifacts (`external-service-impl/rest`, `iotdb-client/cli`, `iotdb-client/service-rpc`, `iotdb-client/session`, `iotdb-core/calc-commons`, `iotdb-core/confignode`, `iotdb-core/datanode`, `iotdb-core/node-commons`), which is uninformative. `example/udf` imports `UnSupportedDataTypeException` while declaring only `udf-api` (`example/udf/pom.xml:31-42`), so it inherits transitively — also uninformative as to origin artifact.

**What would settle it:** the `2.3.2-260616-SNAPSHOT` jars from a reachable Maven repository (or an Apache snapshot mirror), then `unzip -l` on each. I did not attempt to install anything or add a repository, since that would mutate the environment. Until that is available, the correct inventory statement is per-class-to-*group* (`org.apache.tsfile`, both artifacts already listed and both already declared by `iotdb-core/datanode/pom.xml`), not per-class-to-artifact. Asserting a specific artifact for `BytesUtils` or `UnSupportedDataTypeException` right now would be a guess, and both earlier attempts probably differed precisely here — one guessing `common`, the other `tsfile`.

---

## 6. Bottom line

* Routine audited: `QueryDataSetUtils.readTabletValuesFromBuffer(ByteBuffer, TSDataType[], int, int)`, `QueryDataSetUtils.java:622-687`, plus its delegating overload at `:603-611`.
* Inventory entries: 4 — `Binary`, `TSDataType`, `BytesUtils`, `UnSupportedDataTypeException`, all under group `org.apache.tsfile`, all covered by existing `dependencies.json` rows and by the module's own pom declarations.
* Exclusions: 6 categories, each justified above — JDK types, the first-party i18n constants class (filtered out of the SBOM by group), unreached same-file siblings, and the `TabletDecoder` set belonging to the other candidate routine.
* Open, honestly unresolved: artifact-level attribution (`common` vs `tsfile`) for `BytesUtils` and `UnSupportedDataTypeException`; resolvable only with the actual jars.
* No source file, pom, or `dependencies.json` was touched.

I'm digging into the actual tsfile repository structure, trying to pin down whether the `common` module maps to `org.apache.tsfile:common` or just `tsfile`, checking which classes like TSDataType, Binary, BitMap, and Column live where.

Checking pipe-count-point-processor's dependencies, I realize its `iotdb-server` provided scope also brings in tsfile transitively, so it's not clean evidence. But udf-api stands out: it depends only on `org.apache.tsfile:common` with no other entries, so all its imports (Column, ColumnBuilder, TSDataType, Binary, BitMap) must come from `common` alone — strong confirmation that these classes live there.

BytesUtils and UnSupportedDataTypeException remain unresolved, since no common-only module imports them, so I'll leave that ambiguous in my answer. I think I've covered the analysis enough now, so I'll finalize the response, noting also that the stream-based deserialization variant (used from InsertTabletNode) differs from the buffer-based ingestion path only by using DataInputStream/IOException from the JDK.
I have everything needed. Final answer below.

# Dependency inventory — final open entry

**Nothing in the repository was created, edited, deleted or annotated. My diff is empty. Everything below is the deliverable.**

## 1. Settling which routine is meant

"Ingestion side, handles the value columns of an incoming batch" maps to two distinct routines in `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/`, and this ambiguity is the most likely reason the two earlier attempts disagreed:

* **A — `QueryDataSetUtils.readTabletValuesFromBuffer(ByteBuffer, TSDataType[], int, int)`**, `QueryDataSetUtils.java:622-687`. Reached from `StatementGenerator.createStatement(TSInsertTabletsReq)` at `StatementGenerator.java:411-416` (through the `List<Integer>` overload at `QueryDataSetUtils.java:603-611`), and from `InsertTabletNode.java:860` and `:1279`.
* **B — `TabletDecoder.decodeValues(ByteBuffer)`**, `TabletDecoder.java:124-140`, reached from `StatementGenerator.java:363` for the single-tablet `TSInsertTabletReq` path.

I audited **A**. It is the plain, uncompressed, unencoded value-column reader; **B** is the compressed/encoded variant that first calls `uncompress` (`TabletDecoder.java:86-110`) and then `Decoder.getDecoderByType` (`:146`), and therefore pulls in a strictly larger set (`IUnCompressor`, `Decoder`, `TSEncoding`, `CompressionType`, `ReadWriteIOUtils`, `Pair`, `IoTDBRuntimeException`, `TSStatusCode`, `RPCServiceThriftHandlerMetrics`) that is not reachable from A. If the reviewer intended B, this entry must be redone — the two sets are not subsets of each other.

Note also the sibling `readTabletValuesFromStream` (`QueryDataSetUtils.java:689-724`, plus helpers `parseBooleanColumn`…`parseTextColumn` at `:728-783`). It is the stream twin of A used at `InsertTabletNode.java:1238`; its non-JDK identifier set is identical to A's, differing only in JDK types (`java.io.DataInputStream`, `java.io.IOException`).

## 2. Identifiers actually reached in A, quoted from source

* `674: binaryValues[index] = new Binary(binaryValue);` and `669: Binary[] binaryValues = new Binary[size];` → `org.apache.tsfile.utils.Binary`, imported at line 32.
* `631: boolValues[index] = BytesUtils.byteToBool(buffer.get());` → `org.apache.tsfile.utils.BytesUtils`, line 34.
* `679: throw new UnSupportedDataTypeException(` → `org.apache.tsfile.write.UnSupportedDataTypeException`, line 37.
* `624: ByteBuffer buffer, TSDataType[] types, int columns, int size) {`, `627: switch (types[i]) {`, `683: types[i]));` and, in the overload, `606: TSDataType[] dataTypes = new TSDataType[types.size()];` / `608: dataTypes[i] = TSDataType.values()[types.get(i)];` → `org.apache.tsfile.enums.TSDataType`, line 30, together with its constants `628: case BOOLEAN:`, `635: case INT32:`, `636: case DATE:`, `643: case INT64:`, `644: case TIMESTAMP:`, `651: case FLOAT:`, `658: case DOUBLE:`, `665: case TEXT:`, `666: case BLOB:`, `667: case STRING:`, `668: case OBJECT:`.
* `681-683: DataNodeMiscMessages .MISC_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC` → `org.apache.iotdb.db.i18n.DataNodeMiscMessages`, line 23.
* JDK only: `java.nio.ByteBuffer` (`624`, `631`, `639`, `647`, `654`, `661`, `671`, `673`), `java.util.List` (`605`), `java.lang.String.format` (`680`), `java.lang.SuppressWarnings` (`622: @SuppressWarnings("squid:S3776")`).

## 3. Inventory entries

`dependencies.json` is the reference list for the SBOM diff (`src/main/groovy/checkDependencies.groovy`, profile `enable-sbom-check`, `pom.xml:1641-1706`). It holds 158 group:name pairs; the only tsfile ones are `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`.

| Identifier | Entry | Status |
|---|---|---|
| `org.apache.tsfile.utils.Binary` | `org.apache.tsfile:common` | INCLUDED, artifact justified (see §5) |
| `org.apache.tsfile.enums.TSDataType` | `org.apache.tsfile:common` | INCLUDED, artifact justified (see §5) |
| `org.apache.tsfile.utils.BytesUtils` | `org.apache.tsfile:common` **or** `org.apache.tsfile:tsfile` | INCLUDED, artifact **undetermined** |
| `org.apache.tsfile.write.UnSupportedDataTypeException` | `org.apache.tsfile:common` **or** `org.apache.tsfile:tsfile` | INCLUDED, artifact **undetermined** |

Both candidate artifacts are already present in `dependencies.json` and both are declared in `iotdb-core/datanode/pom.xml:51-60`, so the inventory is complete at group:name granularity regardless of how the two undetermined rows resolve. Version is pinned at `pom.xml:148`, `<tsfile.version>2.3.2-260616-SNAPSHOT</tsfile.version>`.

## 4. Exclusions, each with its justification

1. **`java.nio.ByteBuffer`, `java.util.List`, `java.lang.String`, `java.lang.SuppressWarnings`** — JDK. The SBOM filter `src/main/xslt/sbom-filter.xsl` emits one row per `sbom:component`; the JDK is not a component, so no entry can exist. Excluded, not "missing".
2. **`org.apache.iotdb.db.i18n.DataNodeMiscMessages`** — first-party. Defined at `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodeMiscMessages.java:1343` and `.../zh/...:1325`, added as a source root by `iotdb-core/datanode/pom.xml:447-463` (`<source>${project.basedir}/src/main/i18n/${i18n.locale}</source>`). The XSLT selects `sbom:component[sbom:group!='org.apache.iotdb']`, and I confirmed by parsing the file that `dependencies.json` contains zero `org.apache.iotdb:*` entries. Excluded, justified.
3. **Same-file imports not reached from A** — `org.apache.tsfile.block.column.Column` (27), `common.conf.TSFileConfig` (28), `common.conf.TSFileDescriptor` (29), `read.common.block.TsBlock` (31), `utils.BitMap` (33), `utils.Pair` (35), `utils.PublicBAOS` (36), `org.apache.iotdb.commons.exception.IoTDBException` (22), `queryengine.plan.execution.IQueryExecution` (24), `service.rpc.thrift.TSQueryDataSet` (25), `java.io.DataOutputStream`, `java.util.ArrayList`, `java.util.Optional`. All are used elsewhere in `QueryDataSetUtils` (e.g. `BitMap` in `readBitMapsFromBuffer`, `:573-601`) but none appear between lines 603 and 687. Excluded because the audit is per-routine, justified by line-range inspection.
4. **`TabletDecoder`'s dependency set** — excluded because candidate B is not the routine audited. This is the exclusion to revisit first if the reviewer meant B.
5. **Members of included types** — no separate entries; see §5 on granularity.

## 5. What I could and could not settle against source, and why

**Settled.** `org.apache.tsfile:common` is sufficient for `TSDataType` and `Binary`. The decisive evidence is `iotdb-api/udf-api/pom.xml:31-37`: its `<dependencies>` block contains exactly one entry, `org.apache.tsfile:common`, with no other dependency of any kind that could supply tsfile transitively. Its tsfile imports across `src` are exactly `block.column.Column`, `block.column.ColumnBuilder`, `enums.TSDataType`, `utils.Binary`, `utils.BitMap`. Since that module compiles in CI with only `common` on the classpath, `TSDataType` and `Binary` must live in `common`.

**Not settled.** `BytesUtils` and `UnSupportedDataTypeException` cannot be attributed the same way. I checked every `pom.xml` in the tree: the only modules declaring `common` without `tsfile` are `example/pipe-count-point-processor`, `iotdb-api/udf-api` and `library-udf`, and none of the three imports either class. Every module that does import them (`example/session`, `external-service-impl/rest`, `integration-test`, `iotdb-client/cli`, `iotdb-client/service-rpc`, `iotdb-client/session`, `iotdb-core/calc-commons`, `iotdb-core/confignode`, `iotdb-core/datanode`, `iotdb-core/node-commons`) has both artifacts on the classpath, directly or transitively. So the split is invisible from this repository.

**Granularity.** The inventory is sound at **type** granularity only. Member-level facts — that `BytesUtils.byteToBool(byte)`, `TSDataType.values()`, `new Binary(byte[])` and the constant `TSDataType.OBJECT` exist in the pinned `2.3.2-260616-SNAPSHOT` — cannot be verified here: `~/.m2` does not exist, no `*.jar` exists anywhere on the filesystem, and the network is unreachable (`curl` to `repo1.maven.org` returned HTTP `000` with exit code 6, DNS failure). Nothing in this checkout vendors `org.apache.tsfile` sources.

**What would settle the two open rows.** Either of: (a) the `common` and `tsfile` jars for `2.3.2-260616-SNAPSHOT`, so `jar tf` can be read directly; (b) a reachable Maven repository; or (c) a checkout of the upstream `apache/tsfile` repo at that revision, so the module directory holding `utils/BytesUtils.java` and `write/UnSupportedDataTypeException.java` can be read. Absent those, I am recording the two rows as artifact-undetermined rather than guessing, per the "no entry we cannot justify against source" rule.

**What I did not do.** I did not build, install, or generate an SBOM, since that writes to `target/` and mutates the environment. If confirmation via the real SBOM is wanted, the command would be `mvn clean package -DskipTests -P enable-sbom-check` from the repo root, which produces `target/apache-iotdb-parent-2.0.11-SNAPSHOT-sbom.transformed.json` and diffs it against `dependencies.json` — but it requires the Thrift compiler and network access, both unavailable here. No source file, pom, or `dependencies.json` was touched.