I've gathered enough now. I'm finalizing a dependency inventory for the routine, listing each entry with its identifier, line number, and an exclusions list with justification, while double-checking the imports (Objects, List, String.format, LocalDate) and confirming the EMPTY_LOCALDATE and DateUtils usages against the source lines.
I have everything I need. Final answer below.

# Dependency inventory — `TabletInsertionEventParser.filterValueColumnsByRowIndexList(...)`

## 0. Identification of the routine (settled against source)

File: `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`
(file is 699 lines).

Declaration at **line 473**, closing brace at **line 631**. Declared `private static Object`, inside `public abstract class TabletInsertionEventParser` (line 61). This is the ingestion-side routine that handles the value columns of an incoming batch: it projects each value column onto a `rowIndexList` and rebuilds the null bitmap for the projected column.

Signature, verbatim (473–479):

```
  private static Object filterValueColumnsByRowIndexList(
      final TSDataType type,
      final Object originValueColumn,
      final List<Integer> rowIndexList,
      final boolean isSingleOriginValueColumn,
      final BitMap originNullValueColumnBitmap,
      final BitMap nullValueColumnBitmap ) {
```

Call sites — exactly three, all in the same file (`grep -n filterValueColumnsByRowIndexList -r` returns only these plus the declaration):
- **182** — `InsertRowNode` path; passes `true` for `isSingleOriginValueColumn` and `null` for `originNullValueColumnBitmap` (line 183: `originValueDataTypes[i], originValues[i], rowIndexList, true, null, bitMap`).
- **275** — `InsertTabletNode` path; `false` and `getBitMap(originBitMapList, i)`.
- **371** — `Tablet` path; identical shape to 275.

## 1. Inventory — every identifier the routine reaches, at call granularity

### 1a. Internal (same file / same repo)

| Entry | Where used in 473–631 | Definition |
|---|---|---|
| `filterValueColumnsByRowIndexList` (self) | 473 | this file, 473 |
| `isNullValue(BitMap, int)` | 489, 511, 525, 545, 562, 579, 596, 617 | this file, **683–685**: `return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex);` |
| `EMPTY_LOCALDATE` | 512, 526 | this file, **65**: `private static final LocalDate EMPTY_LOCALDATE = LocalDate.of(1000, 1, 1);` |
| `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` | 629 | `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodePipeMessages.java:2277` (`"Data type %s is not supported."`); zh twin at `.../i18n/zh/.../DataNodePipeMessages.java:2115`. Locale-selected source root, wired by `iotdb-core/datanode/pom.xml:458` (`${project.basedir}/src/main/i18n/${i18n.locale}`), default `en` (root `pom.xml:149`), `zh` under profile `with-zh-locale` (root `pom.xml:1986–1991`). |

### 1b. JDK

| Entry | Where | Import |
|---|---|---|
| `java.util.List` / `List.size()` / `List.get(int)` | `rowIndexList.size()` at 487, 488, 501, 510, 524, 543, 544, 560, 561, 577, 578, 594, 595, 613, 614; `rowIndexList.get(i)` at 489, 493, 511, 515, 525, 530, 545, 549, 562, 566, 579, 583, 596, 600, 615, 616, 617, 621 | line 53 |
| `java.lang.Integer` | 476 (type argument `List<Integer>`); also the implicit unboxing on every `rowIndexList.get(i)` used as an array index | implicit |
| `java.util.Objects` — `Objects.isNull` | 615, 616 | line 55 |
| `java.time.LocalDate` | 501, 502, 503, 505, 507, 508 | line 49 |
| `java.lang.String.format` | 628 | implicit |

### 1c. External — `org.apache.tsfile.*`

| Entry | Where | Artifact attribution |
|---|---|---|
| `org.apache.tsfile.enums.TSDataType` + constants `INT32` (481), `DATE` (498), `INT64` (536), `TIMESTAMP` (537), `FLOAT` (555), `DOUBLE` (571), `BOOLEAN` (588), `TEXT` (605), `BLOB` (606), `STRING` (607) | 474, 480–607 | `org.apache.tsfile:common` |
| `org.apache.tsfile.utils.BitMap`, and instance calls `.mark(int)` (491, 513, 527, 547, 564, 581, 598, 619) | 478, 479 + above | `org.apache.tsfile:common` |
| `org.apache.tsfile.utils.Binary`, `Binary.EMPTY_VALUE` (618), `new Binary(byte[])` (621), `.getValues()` (616, 621) | 609–621 | `org.apache.tsfile:common` |
| `org.apache.tsfile.utils.DateUtils.parseIntToLocalDate(int)` | 530 | **Unattributable from this checkout** — see §3 |
| `org.apache.tsfile.write.UnSupportedDataTypeException` | 627 | `org.apache.tsfile:common` (indirect evidence, see §2) |

## 2. How the artifact split was established (this is the part the two earlier attempts could not have done by reading the pom alone)

`iotdb-core/datanode/pom.xml` declares **both** tsfile artifacts — `org.apache.tsfile:common` (lines 53–56) and `org.apache.tsfile:tsfile` (57–61), both at `${tsfile.version}` = `2.3.2-260616-SNAPSHOT` (root `pom.xml:148`). So the datanode pom is silent on which class lives where. TsFile is a separate repository (stated in `CLAUDE.md`); `find . -name TSDataType.java` etc. return nothing, there is no `~/.m2`, and no `tsfile*.jar` anywhere on the filesystem. So I attributed by finding modules in this repo that depend on **exactly one** of the two artifacts and observing what they import:

- `iotdb-api/udf-api/pom.xml` declares `org.apache.tsfile:common` as its **sole** dependency (31–37), and its sources import `org.apache.tsfile.enums.TSDataType`, `org.apache.tsfile.utils.Binary`, `org.apache.tsfile.utils.BitMap` (e.g. `UDAF.java:27` uses `BitMap` in a public signature; `RowImpl.java:124–125` calls `binary.getValues()` and `tsDataType.getType()`). ⇒ `TSDataType`, `BitMap`, `Binary`, `Binary.getValues()` are in **`common`**.
- `example/udf/pom.xml` depends only on `udf-api` (37–40, `provided`) yet imports `org.apache.tsfile.write.UnSupportedDataTypeException`. Since `udf-api`'s only tsfile dependency is `common`, ⇒ `UnSupportedDataTypeException` is in **`common`**, despite its `write` package name.
- Counter-check: `example/schema/pom.xml` depends only on `org.apache.tsfile:tsfile` and imports `org.apache.tsfile.exception.PathParseException` / `read.common.parser.PathNodesGenerator` — a disjoint set, confirming the two artifacts are genuinely split rather than one being a superset in practice.

## 3. Exclusions — entries I cannot justify against source

Per the rule "anything the routine reaches that we cannot justify against source is an exclusion":

1. **`DateUtils.parseIntToLocalDate(int)` (line 530) — artifact attribution excluded.** `org.apache.tsfile.utils.DateUtils` is imported at line 41. Every module in this repo that references it (`external-service-impl/rest`, `integration-test`, `iotdb-client/{cli,jdbc,service-rpc,session,subscription}`, `iotdb-core/{calc-commons,datanode,node-commons}`) declares **both** tsfile artifacts, so no single-artifact witness exists. No `common`-only module (`udf-api`, `library-udf`, `example/pipe-count-point-processor`) references `DateUtils`. It is `org.apache.tsfile.utils.*`, like `Binary`/`BitMap`, which *suggests* `common` — but that is inference, not source, and I am recording it as an exclusion rather than a finding. Settled only by inspecting the TsFile 2.3.2-260616-SNAPSHOT artifacts, which are not present.
2. **Behaviour of `BitMap.mark`, `BitMap.isMarked`, `Binary.EMPTY_VALUE`, `TSDataType` enum ordering — excluded.** Referenced but not defined here; no bytecode or sources available to quote.
3. **`Binary.EMPTY_VALUE` as a `common`-artifact member specifically — partial exclusion.** `Binary` itself is attributed via `udf-api`, but no `common`-only module in this repo references the `EMPTY_VALUE` constant (grep over `udf-api`/`library-udf`/`example/udf` returns nothing), so the constant's existence rests on the datanode call site alone.

Explicitly **not** dependencies of this routine, though nearby and likely to have been miscounted by the earlier attempts:
- **`getBitMap(BitMap[], int)` (679–681)** — invoked by the *callers* at lines 280 and 376, never from within 473–631.
- **`fillNullValue(...)` (633–677)** — a sibling in the same `if/else` at the call sites (174, 267, 363), not a callee. It is the only user of `BitMap.markAll()` (639); `markAll` does **not** appear in 473–631.
- `PipeTabletUtils.compactBitMaps` (190, 288, 384), `generateRowIndexList` / `generateFullRowIndexList` (440–471) — caller-side, outside the routine.

## 4. Two source-level observations worth flagging (not fixed — read-only)

- **Formatting will fail `mvn spotless:check`.** Line 479 reads `      final BitMap nullValueColumnBitmap ) {` — a stray space before `)`, confirmed with `cat -A`. Lines **500, 504, 519** are whitespace-only lines inside the `case DATE` block (`awk '/[ \t]+$/'`). The repo runs `spotless:apply`/`spotless:check` per `CLAUDE.md`. I have left both untouched.
- **`case DATE` is the only branch with a runtime type test** (502–503, the sole `instanceof` occurrences in the whole file): it accepts either `LocalDate`/`LocalDate[]` or `int`/`int[]`, converting the latter through `DateUtils.parseIntToLocalDate`. Every other branch casts unconditionally. Correspondingly, `case TEXT/BLOB/STRING` is the only branch whose null test has three terms (615–617: element null, `getValues()` null, *or* the origin bitmap), and the only one that deep-copies (`new Binary(...getValues())`, 621) instead of aliasing.
- **`nullValueColumnBitmap.mark(i)` is dereferenced unguarded** at 491/513/527/547/564/581/598/619, whereas `originNullValueColumnBitmap` is funnelled through the null-tolerant `isNullValue`. That asymmetry is safe only because all three call sites pass a freshly constructed `new BitMap(this.timestampColumn.length)` (172, ~261, 360) — an unenforced caller invariant, not a guarantee of the routine. Note also the index asymmetry: marks use the **destination** index `i`, reads use the **source** index `rowIndexList.get(i)`; the bitmap is sized to `timestampColumn.length` (the filtered length), which is consistent with marking at `i`.