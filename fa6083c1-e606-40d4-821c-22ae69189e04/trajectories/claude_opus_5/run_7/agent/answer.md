I've verified the remaining details—the constructor usage, the odd formatting around line 479, the default branch, and confirmed unused identifiers via the token frequency check. Time to write the final answer now.

# Dependency inventory — `filterValueColumnsByRowIndexList`

## 1. Settling which routine is meant

"Ingestion-side routine that handles value columns of an incoming batch" resolves uniquely to:

- **`private static Object filterValueColumnsByRowIndexList(...)`**
- File: `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`
- **Lines 473–631** (159 lines), inside `public abstract class TabletInsertionEventParser` (declared line 61).
- Checkout `/workspace/apache__iotdb__8e5e8502`, single commit `a7c3998` ("Initial commit").

Other `*ValueColumns*` routines in the tree are query/compaction/read-path, not ingestion, and are therefore out of scope: `SerializableTVList.getValueColumns` (:400), `TsFileInsertionEventTableParserTabletIterator.fillMeasurementValueColumns` (:483), `InnerTimeJoinOperator.buildValueColumns` (:270), `AlignedReadOnlyMemChunk.getValueColumnsDeletionList` (:482), `MemAlignedPageReader.buildValueColumns` (:185), `ModificationUtils.modifyValueColumns` (:115) and `areAllValueColumnsDeleted` (:130), `QueryDataSetUtils.fillValueColumnsAndBitMaps` (:501).

Signature as quoted from source (note the non-canonical space before `)` on line 479, which survives spotless in this checkout):

```
473|  private static Object filterValueColumnsByRowIndexList(
474|      final TSDataType type,
475|      final Object originValueColumn,
476|      final List<Integer> rowIndexList,
477|      final boolean isSingleOriginValueColumn,
478|      final BitMap originNullValueColumnBitmap,
479|      final BitMap nullValueColumnBitmap ) {
```

Three call sites, all in the same file:
- **182** — `InsertRowNode` path: `(originValueDataTypes[i], originValues[i], rowIndexList, true, null, bitMap)` — single-value column, **no origin bitmap**.
- **275** and **371** — tablet/relational paths: `(originValueColumnDataTypes[i], originValueColumns[i], rowIndexList, false, getBitMap(originBitMapList, i), bitMap)`.
In all three, the `null`/`null-type` case is diverted to `fillNullValue` (:633) before the call.

## 2. Inventory, at reference granularity, paired with declaration

### A. Entries justified against in-repo source

1. **`isNullValue(BitMap, int)`** — private static method of the same class, declared at **683**:
   `683|  private static boolean isNullValue(final BitMap bitMap, final int rowIndex) {`
   `684|    return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex);`
   Reached from **489, 511, 525, 545, 562, 579, 596, 617** (8 sites). Three same-named methods elsewhere are name collisions only, not the resolved target: `RelationalInsertTabletNode.isNullValue` (:229, instance, different arity), `SubscriptionRecordHandler.isNullValue` (:434), `PipeParameters.isNullValue` (:330).

2. **`EMPTY_LOCALDATE`** — private static field, declared at **65**:
   `65|  private static final LocalDate EMPTY_LOCALDATE = LocalDate.of(1000, 1, 1);`
   Read at **512** and **526** inside the routine; the only other read in the whole repo is `662` (`Arrays.fill(dates, EMPTY_LOCALDATE)` in `fillNullValue`).

3. **`DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4`** — referenced once, at **629**. Declared **twice**, in two locale source roots that are alternatives, not both compiled:
   - `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodePipeMessages.java:2277` → `"Data type %s is not supported."`
   - `iotdb-core/datanode/src/main/i18n/zh/org/apache/iotdb/db/i18n/DataNodePipeMessages.java:2115` → `"不支持数据类型 %s。"`
   Selection is by `pom.xml:149` `<i18n.locale>en</i18n.locale>`, overridden to `zh` by profile `with-zh-locale` (`pom.xml:1985-1991`), fed into build-helper `add-source` at `iotdb-core/datanode/pom.xml:458`. **This is a genuine two-declaration entry and is a likely source of the earlier reviewers' disagreement** — there is no single declaration site to cite.

### B. JDK entries (resolvable by language rules, no repo artifact needed)

- `java.lang.Object` — return type (473), parameter type (475).
- `java.util.List` (import 53) — parameter type (476); `size()` at **487, 488, 501, 510, 524, 543, 544, 560, 561, 577, 578, 594, 595, 613, 614** (15); `get(int)` at **489, 493, 511, 515, 525, 530, 545, 549, 562, 566, 579, 583, 596, 600, 615, 616, 617, 621** (18).
- `java.lang.Integer` (476) plus implicit `intValue()` unboxing at each of those 18 `get(i)` uses.
- `java.time.LocalDate` (import 49) — 501, 502, 503, 505, 507, 508.
- `java.util.Objects.isNull` (import 55) — **615, 616** only. `Objects.nonNull` is reached indirectly through `isNullValue` (684), not directly in 473–631.
- `java.lang.String.format` — **628**.
- Implicit unboxing of `originValueColumn` in the `isSingleOriginValueColumn` branches: `Integer.intValue()` at **485** and **522**, `Long.longValue()` at **541**, `Float.floatValue()` at **558**, `Double.doubleValue()` at **575**, `Boolean.booleanValue()` at **592**. These are casts of an `Object` to a primitive and are invisible to a grep-based inventory; **this is the second likely axis of the earlier disagreement.**
- Note `Arrays` and `IntPredicate` are imported by the file but are **not** reached from this routine (`Arrays` only at 662/669 in `fillNullValue`; `IntPredicate` only in `compactColumnIndexMapper`).

### C. Exclusions — references verified, declarations NOT justifiable in this checkout

Per your rule (anything the routine reaches that I cannot justify against source is an exclusion, not an entry), the following are recorded as **exclusions**. The tsfile artifacts are declared but physically absent:

- `pom.xml:148` → `<tsfile.version>2.3.2-260616-SNAPSHOT</tsfile.version>`; `iotdb-core/datanode/pom.xml:52-61` declares `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`; both appear in `dependencies.json` (158 entries total).
- There is **no `.m2` repository, no tsfile jar anywhere on the filesystem, no `package org.apache.tsfile` source in the tree, and no JVM installed** (`java: command not found`). The only jars present are four test fixtures under `integration-test/src/test/resources`.
- Consequence: the following are resolved **textually, from import statements only**, never compiler-verified. I can quote the use site but not the declaration:
  - **`TSDataType`** (import 36) — type at 474; `case` labels `INT32` **481**, `DATE` **498**, `INT64` **536**, `TIMESTAMP` **537**, `FLOAT` **554**, `DOUBLE` **571**, `BOOLEAN` **588**, `TEXT` **605**, `BLOB` **606**, `STRING` **607**.
  - **`BitMap`** (import 40) — types at 478, 479; `mark(int)` at **491, 513, 527, 547, 564, 581, 598, 619** (8). `isMarked` is reached only via 684.
  - **`Binary`** (import 39) — **609, 611, 612, 613**; `Binary.EMPTY_VALUE` at **618**; `new Binary(byte[])` at **621**; `getValues()` at **616, 621**.
  - **`DateUtils.parseIntToLocalDate(int)`** (import 41) — **530**, single use.
  - **`UnSupportedDataTypeException(String)`** (import 42) — **627**, single use.

## 3. Two observations worth flagging (reported here, not written into the tree)

1. **`case DATE` (498–535) is the only branch with two mutually exclusive sub-paths writing one output array.** The `instanceof` test at 502–503 picks either a `LocalDate`/`LocalDate[]` source (505–517) or an `int`/`int[]` source requiring `DateUtils.parseIntToLocalDate` (520–532). It is the only place a local named `intValueColumns` is declared twice in the method (483 and 520), and the only branch reading `EMPTY_LOCALDATE`. An inventory taken "per case label" rather than "per reference" will undercount here.

2. **Null-guard asymmetry between `DATE` and the `TEXT`/`BLOB`/`STRING` branch.** The binary branch guards element nullity explicitly (`Objects.isNull(binaryValueColumns[...])` at 615, `Objects.isNull(....getValues())` at 616) *before* consulting the bitmap at 617. The `DATE`/`LocalDate[]` sub-path at 511 consults the bitmap only. So a `null` element in a `LocalDate[]` whose corresponding bit is unmarked in `originNullValueColumnBitmap` propagates as a raw `null` rather than becoming `EMPTY_LOCALDATE` — unlike every other reference-typed branch. Whether this is reachable depends on the `InsertTabletNode`/`Tablet` construction contract, which I cannot settle here because the tsfile classes are not present. I have not changed anything; if you want this pinned down, the missing input is a resolvable `org.apache.tsfile:tsfile:2.3.2-260616-SNAPSHOT` artifact (or its sources) plus a JDK, which would let the whole of section C be promoted from exclusions to justified entries.

No files were created, modified, or deleted; the working tree is unchanged.