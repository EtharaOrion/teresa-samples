I'm confirming that switch statement doesn't have a fall-through bug — the STRING case ends the switch cleanly without needing a break, so that's fine. I also note markNullValue gets called afterward.

One thing worth flagging: dependencies.json only lists 15 non-iotdb coordinates, which seems short given the XSL filter should include tsfile-group dependencies too. I can't verify this without actually running the maven build, so I'll note it as unverifiable rather than assert a bug. Time to write up the final answer.
Final answer below.

# Dependency‑inventory review: the ingestion‑side "value columns of the incoming batch" routine

## 1. Settling which routine is meant (why the two earlier attempts disagreed)

Grepping `ValueColumns|valueColumns` across the tree and filtering to ingestion‑side code leaves exactly two credible candidates:

| Candidate | File | Lines | What it is given |
|---|---|---|---|
| `filterValueColumnsByRowIndexList` | `iotdb-core/datanode/.../pipe/event/common/tablet/parser/TabletInsertionEventParser.java` | 473–631 | ONE already‑materialised value column (`final Object originValueColumn`) plus a `List<Integer> rowIndexList` |
| `fillMeasurementValueColumns` | `iotdb-core/datanode/.../pipe/event/common/tsfile/parser/table/TsFileInsertionEventTableParserTabletIterator.java` | 483–558 | `final BatchData data` — an **incoming batch** — plus the destination `Tablet` and `rowIndex` |

The phrase that settles it is "value columns **of an incoming batch**". Only `fillMeasurementValueColumns` takes a batch: its first parameter is literally `final BatchData data` (line 484), and it is driven row‑by‑row from `buildNextTablet()` at line 335 while walking `batchData`. `filterValueColumnsByRowIndexList` never sees a batch — it is handed a single column object plus a row‑index list, one column at a time, from the three `parse(...)` overloads (call sites at lines 182, 275, 371). The two earlier reviews almost certainly split on this: both routines are `private`, both live under `pipe/event/common/.../parser/`, both are `TSDataType` switches, both end in `throw new UnSupportedDataTypeException(...)`, and both handle the identical ten enum arms. The distinguishing evidence is the parameter list, not the shape of the body.

Verified single call site: `grep -rn "fillMeasurementValueColumns" --include=*.java .` returns exactly two lines — the definition (483) and the one call (335). Nothing in tests.

## 2. The entry, quoted from source

```java
  private boolean fillMeasurementValueColumns(
      final BatchData data, final Tablet tablet, final int rowIndex) {
```

`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tsfile/parser/table/TsFileInsertionEventTableParserTabletIterator.java`, signature 483–484, body 485–557, closing brace 558.

## 3. Inventory — every identifier the routine reaches, paired with its declaration

**Locals / parameters (in scope, not inventory entries):** `data`, `tablet`, `rowIndex` (484); `primitiveTypes` (485); `needFillTime` (487); `hasNonDeletedField` (488); `i`, `size` (490); `primitiveType` (491); `isDeleted` (493); `binary` (542).

**Enclosing‑class fields:**
- `dataTypeList` — declared line 108, `private List<TSDataType> dataTypeList;`. Reached at 488, 490, 498, 502, 509, 512, 516, 523, 529, 533, 537, 547.
- `deviceIdSize` — declared line 110, `private int deviceIdSize;`. Reached at 488, 490, 492.
- `modsInfoList` — declared line 112, `private List<ModsOperationUtil.ModsInfo> modsInfoList;`. Reached at 493.

**Same‑module IoTDB types:**
- `PipeTabletUtils` — import line 24, `org.apache.iotdb.db.pipe.event.common.tablet.PipeTabletUtils` (`public final class`, declared at line 41 of that file). Two members reached: `putValue` (declared 164–199) at 502, 511, 515, 519, 528, 532, 536, 543; `markNullValue` (declared 151–157) at 504.
- `ModsOperationUtil` — import line 26. One member reached: `isDelete` (declared line 166) at 493. The nested `ModsInfo` (declared line 272) is reached only as the type argument of `modsInfoList`, never constructed or dereferenced here.
- `DataNodePipeMessages` — import line 23, `org.apache.iotdb.db.i18n.DataNodePipeMessages`. One constant reached: `UNSUPPORTED` at 554, declared line 382 of `src/main/i18n/en/.../DataNodePipeMessages.java` as `public static final String UNSUPPORTED = "UnSupported";`. This class is **generated per locale** — `src/main/i18n/${i18n.locale}` is added as a source root by `build-helper-maven-plugin` at `iotdb-core/datanode/pom.xml:458`, with `i18n.locale` defaulting to `en` (`pom.xml:149`) and switched to `zh` by a profile at `pom.xml:1988`. It is not a jar dependency and correctly does not appear in `dependencies.json`.

**External (`org.apache.tsfile`) types:**
- `TsPrimitiveType` — import 53. Members reached: `getBoolean` (512), `getInt` (516, 524), `getLong` (529), `getFloat` (533), `getDouble` (537), `getBinary` (542), `getDataType` (554). Also used as the array element type at 485–486.
- `BatchData` — import 44. Members reached: `getVector` (486) and `currentTime` (493).
- `Binary` — import 50. Members reached: `EMPTY_VALUE` (502, 549) and `getValues` (548). Declared type of the local `binary` at 542.
- `DateUtils` — import 51. Exactly one member: `parseIntToLocalDate` (524), on the `DATE` arm only.
- `UnSupportedDataTypeException` — import 54, `org.apache.tsfile.write.UnSupportedDataTypeException`. Constructed at 553 in the `default` arm.
- `Tablet` — import 55. Parameter type at 484; **no member is invoked on it inside this routine** — every mutation goes through `PipeTabletUtils`.
- `TSDataType` — import 35. Reached only as the element type of `dataTypeList` and via its constants in the two switches: `TEXT`/`BLOB`/`STRING` (499–501 and 539–541), `BOOLEAN` (510), `INT32` (514), `DATE` (518), `INT64` (526), `TIMESTAMP` (527), `FLOAT` (531), `DOUBLE` (535).

**JDK:**
- `Objects` — import 64, `java.util.Objects`. Members: `nonNull` (486), `isNull` (548, twice on one line).

**Dependency provenance, stated plainly:** every external identifier above resolves to `org.apache.tsfile`, supplied by the two `<dependency>` blocks at `iotdb-core/datanode/pom.xml:52–61` (`org.apache.tsfile:common` and `org.apache.tsfile:tsfile`) at `${tsfile.version}` = `2.3.2-260616-SNAPSHOT` (`pom.xml:148`).

## 4. Exclusions — written disagreement, one line each

- **`LocalDate` / `java.time`.** Excluded, and this is the entry I expect to be argued about. The `DATE` arm (518–525) passes the result of `DateUtils.parseIntToLocalDate(...)` straight into `putValue` as an `Object`; the routine never names `LocalDate`, and the file does not import it. The cast `(LocalDate) value` lives one hop away, at `PipeTabletUtils.java:178`. Inventorying `LocalDate` here would be crossing the routine boundary.
- **`org.apache.tsfile:*` is absent from `dependencies.json`.** The file lists 15 coordinates and none is a tsfile artifact, even though `src/main/xslt/sbom-filter.xsl` only excludes `sbom:group = 'org.apache.iotdb'`. I cannot justify this against source alone — resolving it requires actually running `mvn package -P enable-sbom-check` and reading `target/apache-iotdb-...-sbom.transformed.json`, which I did not do (read‑only, and no local Maven repository exists: `~/.m2` is absent). I am recording it as an open exclusion rather than guessing that tsfile is deliberately allow‑listed.
- **`PipeTabletUtils.unmarkNullValue`** (declared 201) — reached only transitively, from inside `putValue` at line 198. Not an entry.
- **`fillDeviceIdColumns`** (declared 560) and **`PipeTabletUtils.putTimestamp`** — siblings called by `buildNextTablet` at 336–337, *guarded by this routine's return value*, but never called from within it.
- **`internMeasurementName`** (476–481) and **`TabletStringInternPool`** (import 25) — adjacent in the file, not reached.
- **Imports the file carries but this routine does not touch:** `PatternTreeMap` (22), `PipeDataNodeResourceManager` (27), `PipeMemoryBlock` (28), `PipeMemoryWeightUtil` (29), `PipeException` (30), `ColumnCategory`, `AbstractAlignedChunkMetadata`, `IChunkMetadata`, `IDeviceID`, `MetadataIndexNode`, `TableSchema`, `TsFileMetadata`, `TsFileSequenceReader`, `IMetadataQuerier`.
- **`filterValueColumnsByRowIndexList` and `fillNullValue`** in `TabletInsertionEventParser` — the rejected candidate and its sibling. No call path connects them to this routine.

## 5. Two source facts worth the reviewer's attention (observations only, nothing changed)

1. **The null/deleted switch at 498–503 has no `default` and no `break`.** It is legal — `case STRING:` falls into the single `putValue` call which is the last statement of the switch — but its effect is asymmetric: for `TEXT`/`BLOB`/`STRING` a null/deleted cell is written as `Binary.EMPTY_VALUE` *and* marked null (504), whereas for every other type the slot is left at whatever the freshly allocated `Tablet` array holds and only the bitmap is marked. `putValue` calls `unmarkNullValue` (198), so the ordering matters: `putValue` at 502 runs *before* `markNullValue` at 504, and the mark therefore survives. If those two lines were ever reordered the null flag would be silently cleared for text columns.
2. **The return value conflates two conditions.** `hasNonDeletedField` is seeded `dataTypeList.size() == deviceIdSize` (488) — i.e. `true` when the table has no field columns at all — and the routine returns `needFillTime || hasNonDeletedField` (557). So a row whose every field is deleted still returns `true` if the schema is device‑columns‑only, and `buildNextTablet` will then stamp a timestamp for it (337). Whether that is intended is a question for the pipe owners; I am reporting it, not proposing a change.

No files were created, modified, or deleted; my diff is empty.