I've finished the audit. No files were created, edited, or otherwise touched — `git status --porcelain` is empty.

## The routine, identified from source

There is exactly one ingestion-side routine that handles the value columns of an incoming batch and matches the description. `grep -rn "filterValueColumnsByRowIndexList" --include=*.java .` returns four hits, all in a single file:

`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`

- declaration: lines **473–631**
- call sites: **182** (`InsertRowNode` path, passes `rowIndexList, true, null, bitMap`), **275** (`InsertTabletNode` path, passes `rowIndexList, false, getBitMap(originBitMapList, i), bitMap`), **371** (`Tablet` path, same shape as 275)

Signature as written (note the non-canonical space before `)` on line 479 — the file is not spotless-clean here):

```java
473:  private static Object filterValueColumnsByRowIndexList(
474:      final TSDataType type,
475:      final Object originValueColumn,
476:      final List<Integer> rowIndexList,
477:      final boolean isSingleOriginValueColumn,
478:      final BitMap originNullValueColumnBitmap,
479:      final BitMap nullValueColumnBitmap ) {
```

## Inventory — every out-of-file identifier the routine reaches directly

Paired with the import that binds it, at identifier granularity. Every entry is quoted from source.

| # | Identifier | Bound by | Reached at (lines) | Quote |
|---|---|---|---|---|
| 1 | `TSDataType` (type) | `36:import org.apache.tsfile.enums.TSDataType;` | 474 | `final TSDataType type,` |
| 2 | `TSDataType.INT32/DATE/INT64/TIMESTAMP/FLOAT/DOUBLE/BOOLEAN/TEXT/BLOB/STRING` (enum constants, unqualified as `switch` labels) | same import | 481, 498, 536, 537, 554, 571, 588, 605, 606, 607 | `case INT32:` … `case STRING:` |
| 3 | `BitMap` (type) | `40:import org.apache.tsfile.utils.BitMap;` | 478, 479 | `final BitMap originNullValueColumnBitmap,` |
| 4 | `BitMap.mark(int)` | same import | 491, 513, 527, 547, 564, 581, 598, 619 | `nullValueColumnBitmap.mark(i);` |
| 5 | `Binary` (type + array type) | `39:import org.apache.tsfile.utils.Binary;` | 609, 611, 612, 613 | `final Binary[] binaryValueColumns =` |
| 6 | `Binary(byte[])` ctor | same import | 621 | `valueColumns[i] = new Binary(binaryValueColumns[rowIndexList.get(i)].getValues());` |
| 7 | `Binary.EMPTY_VALUE` | same import | 618 | `valueColumns[i] = Binary.EMPTY_VALUE;` |
| 8 | `Binary.getValues()` | same import | 616, 621 | `\|\| Objects.isNull(binaryValueColumns[rowIndexList.get(i)].getValues())` |
| 9 | `DateUtils.parseIntToLocalDate(int)` | `41:import org.apache.tsfile.utils.DateUtils;` | **530 only** | `DateUtils.parseIntToLocalDate(intValueColumns[rowIndexList.get(i)]);` |
| 10 | `UnSupportedDataTypeException(String)` | `42:import org.apache.tsfile.write.UnSupportedDataTypeException;` | 627 | `throw new UnSupportedDataTypeException(` |
| 11 | `LocalDate` (type, array type, cast) | `49:import java.time.LocalDate;` | 501, 502, 503, 505, 507, 508 | `final LocalDate[] valueColumns = new LocalDate[rowIndexList.size()];` |
| 12 | `List` / `List.get` / `List.size` | `53:import java.util.List;` | 476; 489/493/511/515/525/530/545/549/562/566/579/583/596/600/615/616/617/621; 487/488/501/510/524/543/544/560/561/577/578/594/595/613/614 | `final List<Integer> rowIndexList,` |
| 13 | `Integer` (type argument; also auto-unboxed at every `rowIndexList.get(i)` array index) | `java.lang`, implicit | 476 + all `get` sites above | `final List<Integer> rowIndexList,` |
| 14 | `Objects.isNull` | `55:import java.util.Objects;` | 615, 616 | `if (Objects.isNull(binaryValueColumns[rowIndexList.get(i)])` |
| 15 | `String.format` | `java.lang`, implicit | 628 | `String.format(` |
| 16 | `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` | `26:import org.apache.iotdb.db.i18n.DataNodePipeMessages;` | 629 | `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4, type));` |

Two same-file (in-class, not out-of-file) dependencies, listed for completeness because both earlier attempts plausibly treated them inconsistently:

- `EMPTY_LOCALDATE` — declared `65:  private static final LocalDate EMPTY_LOCALDATE = LocalDate.of(1000, 1, 1);`, reached at 512 and 526.
- `isNullValue(BitMap, int)` — declared at 683–685, called at 489, 511, 525, 545, 562, 579, 596, 617.

## Exclusions, with the justification each one turns on

- **`BitMap.isMarked` and `Objects.nonNull` — excluded.** Neither appears anywhere in 473–631. They are reached only *transitively*, through the private helper: `684:    return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex);`. At the "not every function directly" granularity you asked for, they are out.
- **`getBitMap` (679–681) — excluded.** It is applied at the call sites (275, 371), not inside the routine; the routine receives the already-resolved `BitMap`.
- **`fillNullValue`, `PipeTabletUtils.compactBitMaps`, `InsertRowNode`, `InsertTabletNode`, `Tablet`, `IMeasurementSchema`, `ColumnCategory`, `IDeviceID`, `IntStream`, `Collectors` — excluded.** All are used elsewhere in the file (the `parse` overloads and the sibling branch of the `Objects.isNull(...)` guard at 173/265/361), never within 473–631. `IntStream` in particular is confirmed absent from the routine.
- **`LOGGER` / `DataNodePipeMessages.INSERTROWNODE_IS_PARSED_TO_ZERO_ROWS_ACCORDING` — excluded.** Post-loop reporting in `parse`, not in the routine. Note that `DataNodePipeMessages` as a *class* is still entry 16, via a different constant.

## The one entry I cannot justify against source, and why

Every tsfile identifier above (entries 1–10) resolves to package `org.apache.tsfile.*`, but **I cannot determine from this checkout which Maven artifact supplies which class.** `iotdb-core/datanode/pom.xml` declares both, unversioned-by-property:

```
52-56:  org.apache.tsfile:common      ${tsfile.version}
57-61:  org.apache.tsfile:tsfile      ${tsfile.version}
```

with `148:        <tsfile.version>2.3.2-260616-SNAPSHOT</tsfile.version>` in the root pom, and `dependencies.json` lists both `"org.apache.tsfile:common"` and `"org.apache.tsfile:tsfile"` as known SBOM entries. There are **zero** `org/apache/tsfile/` sources tracked in this repo (`git ls-files | grep -c org/apache/tsfile/` → `0`), no tsfile jar anywhere on the filesystem, no `~/.m2`, and no `java`/`javap`/`mvn` on PATH. So the `common`-vs-`tsfile` split is not derivable from source here.

The best circumstantial evidence available, from modules that depend on `org.apache.tsfile:common` *without* `:tsfile` (`iotdb-api/udf-api`, `library-udf`, `example/pipe-count-point-processor`, and `example/udf` transitively via `udf-api`): those modules successfully import `TSDataType`, `Binary`, `BitMap`, `Column`, `ColumnBuilder`, `Tablet`, `MeasurementSchema`, and `UnSupportedDataTypeException` (`example/udf/.../UDAFExample.java:33`), and call `Binary.getValues()` and `new Binary(byte[])`. That makes entries 1–8 and 10 *probably* `:common`. But **`DateUtils` never appears in any common-only module** — every one of the ten modules using `org.apache.tsfile.utils.DateUtils` also declares `:tsfile`. So entry 9 is genuinely unresolvable here. Resolving it needs either the tsfile source tree at tag `2.3.2-260616-SNAPSHOT` or the two jars to inspect. I am flagging it rather than guessing.

## Why the two earlier attempts most likely disagreed

In descending order of likelihood:

1. **The `DATE` case is bimodal, and one arm is easy to miss.** Lines 502–503 discriminate at runtime:
   ```java
   502:  if (isSingleOriginValueColumn && originValueColumn instanceof LocalDate
   503:      || !isSingleOriginValueColumn && originValueColumn instanceof LocalDate[]) {
   ```
   The `if` arm (505–518) copies `LocalDate[]` directly; the `else` arm (519–532) reads `int[]` and converts. `DateUtils` occurs **exactly once in the whole routine, at 530, inside that `else` arm**. Any audit that stopped at the first `return valueColumns;` for `case DATE:` (line 534 is the only one — the arms share it) or that assumed one array type per case label drops entry 9 entirely. This is the single most probable source of the disagreement.
2. **Transitive vs. direct treatment of `isNullValue`.** It is called eight times inside the routine, but `BitMap.isMarked` and `Objects.nonNull` live only in the helper at 683–685. Counting one hop out yields a strictly larger inventory than counting zero hops. Both are defensible; they are not the same list. I counted zero hops and said so.
3. **`Objects` double-jeopardy.** `Objects.isNull` *is* reached directly, but only at 615–616, in the `TEXT/BLOB/STRING` arm, and for a null/empty-payload check that is unrelated to the bitmap. An auditor who resolved point 2 by excluding `Objects.nonNull` may have excluded `Objects` wholesale and lost entry 14.
4. **`TSDataType` counted once vs. per-constant.** The type reference at 474 and the ten unqualified `case` labels are the same import but different identifiers; entries 1 and 2 will collapse into one row under a coarser rule.
5. **`Integer` unboxing.** `rowIndexList.get(i)` is used as an array index eighteen times; whether that counts as reaching `Integer` (entry 13) or is invisible sugar is a granularity call, not a fact about the source.

If the reviewer wants the inventory settled at a single granularity, the choice that has to be written down explicitly is (a) direct-only vs. one-hop-transitive, and (b) type-reference vs. per-member. Fixing those two makes the list reproducible; leaving them open reproduces exactly the disagreement you're arbitrating.

I've confirmed the method details—filterValueColumnsByRowIndexList spans lines 473–631 as a private static method in TabletInsertionEventParser.java, called at lines 182, 275, and 371. I'm ready to finalize the answer with these verified facts.

# Dependency inventory — ingestion-side value-column routine

**Working tree unchanged:** `git status --porcelain` is empty. Nothing was created, edited, or annotated.

## 1. Which routine this is (settled against source, not against the two prior attempts)

`grep -rn "filterValueColumnsByRowIndexList" --include=*.java .` returns exactly four hits, all in one file:

`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`

* declaration: **lines 473–631**
* call sites: **182** (`InsertRowNode` path — `rowIndexList, true, null, bitMap`), **275** (`InsertTabletNode` path — `rowIndexList, false, getBitMap(originBitMapList, i), bitMap`), **371** (`Tablet` path, same shape as 275)

Signature as written (line 479 quoted verbatim, including its non-canonical `nullValueColumnBitmap ) {` spacing):

```java
473:  private static Object filterValueColumnsByRowIndexList(
474:      final TSDataType type,
475:      final Object originValueColumn,
476:      final List<Integer> rowIndexList,
477:      final boolean isSingleOriginValueColumn,
478:      final BitMap originNullValueColumnBitmap,
479:      final BitMap nullValueColumnBitmap ) {
```

## 2. Inventory — out-of-file identifiers the routine reaches directly

Paired with import and every reaching line. Type-reference and member-access are listed separately (see §4, disagreement axis (b)).

| # | Identifier | Import / declaration | Lines in 473–631 |
|---|---|---|---|
| 1 | `TSDataType` (type) | `36:import org.apache.tsfile.enums.TSDataType;` | 474 `final TSDataType type,` |
| 2 | `TSDataType` constants `INT32, DATE, INT64, TIMESTAMP, FLOAT, DOUBLE, BOOLEAN, TEXT, BLOB, STRING` | same import | 481, 498, 536, 537, 554, 571, 588, 605, 606, 607 |
| 3 | `BitMap` (type) | `40:import org.apache.tsfile.utils.BitMap;` | 478, 479 |
| 4 | `BitMap.mark(int)` | same import | 491, 513, 527, 547, 564, 581, 598, 619 — `nullValueColumnBitmap.mark(i);` |
| 5 | `Binary` (type, array type, cast) | `39:import org.apache.tsfile.utils.Binary;` | 609, 611, 612, 613 |
| 6 | `Binary.EMPTY_VALUE` | same import | 618 `valueColumns[i] = Binary.EMPTY_VALUE;` |
| 7 | `new Binary(byte[])` | same import | 621 |
| 8 | `Binary.getValues()` | same import | 616, 621 |
| 9 | `DateUtils.parseIntToLocalDate(int)` | `41:import org.apache.tsfile.utils.DateUtils;` | **530 only** |
| 10 | `UnSupportedDataTypeException` | `42:import org.apache.tsfile.write.UnSupportedDataTypeException;` | 627 |
| 11 | `LocalDate` (type, array, cast, `instanceof`) | `49:import java.time.LocalDate;` | 501, 502, 503, 505, 507, 508 |
| 12 | `List<Integer>` / `List.get` / `List.size` | `53:import java.util.List;` | 476; `.get` at 489, 493, 511, 515, 525, 530, 545, 549, 562, 566, 579, 583, 596, 600, 615, 616, 617, 621; `.size` at 487, 488, 501, 510, 524, 543, 544, 560, 561, 577, 578, 594, 595, 613, 614 |
| 13 | `Integer` (type argument) | `java.lang` | 476 |
| 14 | `Objects.isNull` | `55:import java.util.Objects;` | 615, 616 |
| 15 | `String.format` | `java.lang` | 628 |
| 16 | `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` | `26:import org.apache.iotdb.db.i18n.DataNodePipeMessages;` | 629 |

In-file, same-class (listed for completeness, not external):
* `EMPTY_LOCALDATE` — `65: private static final LocalDate EMPTY_LOCALDATE = LocalDate.of(1000, 1, 1);` — read at 512, 526.
* `isNullValue(BitMap, int)` — declared 683–685, called at 489, 511, 525, 545, 562, 579, 596, 617.

## 3. Exclusions, each with its reason from source

* **`BitMap.isMarked` and `Objects.nonNull` — excluded.** Zero occurrences in 473–631. Reached only one hop out, via `683: private static boolean isNullValue(final BitMap bitMap, final int rowIndex) { 684: return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex); }`. Note `Objects` *is* in the inventory (entry 14) on the strength of `Objects.isNull` at 615–616, which is direct; `Objects.nonNull` is not.
* **`getBitMap` (679–681) — excluded.** It runs at the call sites (275, 371) to produce the argument; the routine never calls it.
* **`fillNullValue`, `PipeTabletUtils.compactBitMaps`, `InsertRowNode`, `InsertTabletNode`, `Tablet`, `IMeasurementSchema`, `ColumnCategory`, `IDeviceID`, `StringArrayDeviceID`, `IntStream`, `Collectors`, `LOGGER`, `TsTableColumnCategory`, `IllegalPathException` — excluded.** All imported by the file and used elsewhere in it; none appears between 473 and 631. `fillNullValue` in particular is the *sibling* of this routine at the same call sites (lines ~173–179, 265–272, 361–368) — the most tempting false positive.
* **`DataNodePipeMessages.INSERTROWNODE_IS_PARSED_TO_ZERO_ROWS_ACCORDING` — excluded**, though the class is in as entry 16 for a different constant.

## 4. The one entry I cannot justify against source

**Which Maven artifact supplies each `org.apache.tsfile.*` class (entries 1–10).** `iotdb-core/datanode/pom.xml` declares both, at the same version property:

```
52-56:  <groupId>org.apache.tsfile</groupId> <artifactId>common</artifactId> <version>${tsfile.version}</version>
57-61:  <groupId>org.apache.tsfile</groupId> <artifactId>tsfile</artifactId>  <version>${tsfile.version}</version>
```

with `148: <tsfile.version>2.3.2-260616-SNAPSHOT</tsfile.version>` in the root pom, and both coordinates present in `dependencies.json` (`"org.apache.tsfile:common"`, `"org.apache.tsfile:tsfile"`). The split is not derivable here: zero `org/apache/tsfile/` sources are tracked (`git ls-files | grep -c "org/apache/tsfile/"` → `0`), no tsfile jar exists on the filesystem, there is no `~/.m2`, and `java`/`javap`/`mvn` are absent from PATH.

Circumstantially — and I label this circumstantial, not a finding — the modules depending on `:common` *without* `:tsfile` (`iotdb-api/udf-api`, `library-udf`, `example/pipe-count-point-processor`, plus `example/udf` transitively through `udf-api`) do import `TSDataType`, `Binary`, `BitMap`, `Tablet`, `MeasurementSchema`, `Column`, `ColumnBuilder` and `UnSupportedDataTypeException`, and do call `Binary.getValues()` and `new Binary(byte[])`. That suggests entries 1–8 and 10 resolve from `:common`. But none of those modules touches `DateUtils`, `BitMap.mark`, or `Binary.EMPTY_VALUE` anywhere, so entry 9 and the specific members in entries 4 and 6 stay unresolved. **Settling it requires the tsfile 2.3.2-260616-SNAPSHOT jars** — then `javap -cp common.jar org.apache.tsfile.utils.DateUtils` (etc.) answers it per class in one pass. I did not fabricate an attribution to close the row.

## 5. Why the two earlier attempts most likely disagreed

In descending likelihood:

1. **The `case DATE:` arm is bimodal and the second half is easy to miss.** Lines 502–503 discriminate at runtime — `if (isSingleOriginValueColumn && originValueColumn instanceof LocalDate || !isSingleOriginValueColumn && originValueColumn instanceof LocalDate[])` — taking a `LocalDate[]` path (505–518), and the `else` at 519–532 taking an `int[]` path. An audit that stops at the first `return valueColumns;` per `case`, or that assumes one array type per label, loses **`DateUtils` entirely**: line 530 is its only occurrence in the routine, and `DateUtils` appears nowhere else in the arms. This alone produces a 16-entry vs 15-entry disagreement.
2. **Direct-only vs. one-hop-transitive counting of `isNullValue`.** `BitMap.isMarked` and `Objects.nonNull` live only in the 683–685 helper. One convention admits them, the other rejects them; both are defensible, and neither attempt would state which it used.
3. **`Objects` half-in/half-out.** An auditor who rejected `Objects.nonNull` on transitivity grounds may have dropped `Objects` wholesale and lost the direct `Objects.isNull` at 615–616 (entry 14).
4. **Type-reference vs. per-member granularity for `TSDataType` and `Binary`.** Entries 1+2 collapse to one row under type granularity; entries 5–8 collapse to one row. Two attempts using different granularity produce different counts from identical readings.
5. **`Integer` (entry 13) and `String.format` (entry 15).** `java.lang` implicits are routinely omitted; `rowIndexList.get(i)` also performs an implicit `Integer` unboxing at every array index, which some conventions count and some do not.

The disagreement is a convention gap on two axes — (a) direct vs. one-hop-transitive, (b) type-reference vs. per-member — plus the genuine DATE-branch reading error in (1). Fixing the axes makes the count reproducible; leaving them open reproduces the disagreement no matter how carefully either side reads.

## 6. Incidental observations (reported here, not acted on)

* Line 479 reads `final BitMap nullValueColumnBitmap ) {` — a stray space before `)`, inconsistent with the rest of the file and with the Spotless/`google-java-format` style the repo enforces per `AGENTS.md`. `mvn spotless:check` would flag it.
* Lines 500, 504, 509 and 519 are blank lines inside the `case DATE:` block, and lines 686–688 are three consecutive blank/whitespace lines (`686:''`, `687:'  '`, `688:''`) between `isNullValue` and `processRowByRow`; line 687 is whitespace-only. Also likely Spotless findings.

I am flagging these because they bear on whether this file is currently in a committable state; I have not changed them.