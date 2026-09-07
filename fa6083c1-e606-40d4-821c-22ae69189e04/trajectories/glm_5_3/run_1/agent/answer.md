Now I have the complete inventory of function calls inside `filterValueColumnsByRowIndexList`. Let me consolidate.

The routine: `TabletInsertionEventParser.filterValueColumnsByRowIndexList` — lines 473–632 in `/workspace/apache__iotdb__8e5e8502/iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`.

This is the ingestion-side routine that handles the value columns of an incoming batch (an `InsertRowNode` / `InsertTabletNode` / `Tablet` being parsed into pipe events), filtering each value column by a row index list and maintaining null bitmaps.

Distinct function calls made directly by the routine (not counting calls made by those callees — the user said "not every function directly, paired with ... and at granularity" — the phrasing is garbled but the instruction says the inventory should list what the routine itself calls, and exclusions are anything the routine reaches that cannot be justified).

Let me enumerate the distinct call sites:

In-repo (same repository, this source tree):
1. `isNullValue(BitMap, int)` — private static, same file, line 683. In repo.
2. `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` — this is a field access, not a function call. Actually it's a constant reference. Hmm, it's a static field, not a method call. So not a function call.

External (from org.apache.tsfile, an external dependency — `tsfile` artifact, declared in datode pom.xml with `${tsfile.version}`):
1. `rowIndexList.get(int)` — `java.util.List.get` — JDK.
2. `rowIndexList.size()` — `java.util.List.size` — JDK.
3. `nullValueColumnBitmap.mark(int)` — `org.apache.tsfile.utils.BitMap.mark` — external dependency.
4. `Objects.isNull(Object)` — `java.util.Objects.isNull` — JDK.
5. `binaryValueColumns[...].getValues()` — `org.apache.tsfile.utils.Binary.getValues` — external dependency.
6. `Binary.EMPTY_VALUE` — static field access on `org.apache.tsfile.utils.Binary` — external, but a field not a method.
7. `new Binary(byte[])` — constructor of `org.apache.tsfile.utils.Binary` — external.
8. `String.format(String, Object...)` — JDK.
9. `DateUtils.parseIntToLocalDate(int)` — `org.apache.tsfile.utils.DateUtils` — external dependency.
10. `new UnSupportedDataTypeException(String)` — constructor of `org.apache.tsfile.write.UnSupportedDataTypeException` — external.

Also array constructors `new int[]`, etc. — language-level, not functions.

So the complete inventory of *function/method calls* in the routine:

| Call | Resolved to | In-repo? |
|---|---|---|
| `rowIndexList.size()` | `java.util.List#size()` | JDK (external) |
| `rowIndexList.get(int)` | `java.util.List#get(int)` | JDK (external) |
| `isNullValue(BitMap, int)` | `TabletInsertionEventParser#isNullValue` (line 683, same file) | **In-repo** |
| `nullValueColumnBitmap.mark(int)` | `org.apache.tsfile.utils.BitMap#mark(int)` | External (tsfile) |
| `Objects.isNull(Object)` ×2 | `java.util.Objects#isNull` | JDK (external) |
| `DateUtils.parseIntToLocalDate(int)` | `org.apache.tsfile.utils.DateUtils#parseIntToLocalDate` | External (tsfile) |
| `Binary.getValues()` | `org.apache.tsfile.utils.Binary#getValues()` | External (tsfile) |
| `new Binary(byte[])` | `org.apache.tsfile.utils.Binary#<init>(byte[])` | External (tsfile) |
| `String.format(...)` | `java.lang.String#format` | JDK (external) |
| `new UnSupportedDataTypeException(String)` | `org.apache.tsfile.write.UnSupportedDataTypeException#<init>` | External (tsfile) |

Plus non-call identifier references: `Binary.EMPTY_VALUE` (static field, tsfile), `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` (static field, in-repo: `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodePipeMessages.java` line 2277), and `EMPTY_LOCALDATE` (private static field in same file, line 65) — these are field reads, not function calls.

The only call that resolves to a function *defined in this repository* is `isNullValue` (private static helper in the same file, line 683-685). Its body itself calls `Objects.nonNull(BitMap)` and `BitMap.isMarked(int)` — both external/JDK — but the user said not to go into transitively-called functions, so that's out of scope.

Everything else the routine reaches is either a JDK method (`List.get`, `List.size`, `Objects.isNull`, `String.format`) or an external Apache TsFile dependency method (`BitMap.mark`, `DateUtils.parseIntToLocalDate`, `Binary.getValues`, `Binary` ctor, `UnSupportedDataTypeException` ctor).

Regarding "exclusions": the instruction (garbled) says something like "anything the routine reaches is an exclusion if we cannot justify it against source [in this repo] — complete and no more/less than truth." So exclusions = calls that do NOT resolve to in-repo definitions. That would be all of the JDK and tsfile ones.

Let me double check `isNullValue` body: 
```java
private static boolean isNullValue(final BitMap bitMap, final int rowIndex) {
    return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex);
}
```
Yes — in-repo definition at line 683.

Also I should double-check whether `Binary.EMPTY_VALUE` is a field — yes, `Binary.EMPTY_VALUE` is a public static final field in tsfile's Binary class. And `new Binary(...)` is a constructor call. Constructors count as function calls at granularity of "call".

Let me also confirm the count from my grep: 18 rowIndexList.get, 15 rowIndexList.size, 8 mark, 8 isNullValue, 2 getValues, 2 Objects.isNull, 1 UnSupportedDataTypeException, 1 String.format, 1 DateUtils.parseIntToLocalDate, 1 Binary (constructor). That's 10 distinct callables.

Wait — 8 isNullValue calls but only 8 mark calls. The type cases: INT32, DATE (two branches: LocalDate and int), INT64/TIMESTAMP, FLOAT, DOUBLE, BOOLEAN, TEXT/BLOB/STRING = that's 8 isNullValue call sites (INT32=1, DATE LocalDate=1, DATE int=1, INT64=1, FLOAT=1, DOUBLE=1, BOOLEAN=1, TEXT=1 → 8). And 8 mark calls. ✓ Consistent.

rowIndexList.get: 18 — INT32 has 2 (isNull arg + value), DATE LocalDate 2, DATE int 2, INT64 2, FLOAT 2, DOUBLE 2, BOOLEAN 2, TEXT 4 (Objects.isNull ×2 use rowIndexList.get, then binaryValueColumns[rowIndexList.get(i)]) → 2*7=14 + 4 = 18 ✓.

size(): 15 — one array alloc + one loop bound per case = 2 per case... 8 cases × 2 = 16? Hmm, INT32: `new int[rowIndexList.size()]` and loop `i < rowIndexList.size()` = 2. DATE: LocalDate alloc (2 uses: `new LocalDate[rowIndexList.size()]` and loop) but the else-branch int loop uses `rowIndexList.size()` in the loop condition too — but the int[] array isn't allocated by size. So DATE: 2 (alloc+loop) + 1 (else loop) = 3. INT64 2, FLOAT 2, DOUBLE 2, BOOLEAN 2, TEXT 2 → 2+3+2+2+2+2+2 = 15 ✓.

Great, consistent.

Now, the deliverable: a dependency inventory of the routine with in-repo vs external/excluded, quoting every identifier. Let me write it up.

Note the user's garbled instruction: "not every function directly, paired with and at granularity" — probably originally "include every function called directly, paired with file and line at fine granularity." And "exclusions written disagreement anything routine reaches is an exclusion as inventory audited entry we cannot justify against source complete and no than truth" — probably "exclusions: anything the routine reaches that we cannot justify against source [in this repo] is an exclusion. The audited inventory must be complete and no more than the truth."

So: complete list, nothing extra, and exclusions = external/unjustifiable-against-this-repo entries.

Let me write the final answer.
I now have complete evidence. Here is the dependency inventory.

## Routine under review

**`TabletInsertionEventParser.filterValueColumnsByRowIndexList`**
- File: `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`
- Lines: **473â632**
- Signature: `private static Object filterValueColumnsByRowIndexList(final TSDataType type, final Object originValueColumn, final List<Integer> rowIndexList, final boolean isSingleOriginValueColumn, final BitMap originNullValueColumnBitmap, final BitMap nullValueColumnBitmap)`

This is the ingestion-side routine that handles the value columns of an incoming batch: it is called from `parse(InsertRowNode)` (line 180) and `parse(InsertTabletNode)` (line 274) to materialize each device's value column arrays, filtered by a row-index list, while maintaining the null bitmaps.

## Complete call inventory (every function this routine calls directly)

| # | Call site (identifier as written) | Resolves to | In this repo? |
|---|---|---|---|
| 1 | `isNullValue(originNullValueColumnBitmap, rowIndexList.get(i))` â 8 sites (lines 489, 511, 523, 545, 562, 580, 597, 617) | `TabletInsertionEventParser#isNullValue(BitMap, int)`, **same file, line 683** | **YES â in repo** |
| 2 | `rowIndexList.size()` â 15 sites | `java.util.List#size()` | No â JDK |
| 3 | `rowIndexList.get(i)` â 18 sites | `java.util.List#get(int)` | No â JDK |
| 4 | `nullValueColumnBitmap.mark(i)` â 8 sites | `org.apache.tsfile.utils.BitMap#mark(int)` | No â tsfile external dep |
| 5 | `Objects.isNull(...)` â 2 sites (lines 615, 616) | `java.util.Objects#isNull(Object)` | No â JDK |
| 6 | `DateUtils.parseIntToLocalDate(intValueColumns[rowIndexList.get(i)])` â 1 site (line 530) | `org.apache.tsfile.utils.DateUtils#parseIntToLocalDate(int)` | No â tsfile external dep |
| 7 | `binaryValueColumns[...].getValues()` â 2 sites (lines 616, 621) | `org.apache.tsfile.utils.Binary#getValues()` | No â tsfile external dep |
| 8 | `new Binary(binaryValueColumns[...].getValues())` â 1 site (line 621) | `org.apache.tsfile.utils.Binary#<init>(byte[])` | No â tsfile external dep |
| 9 | `String.format(DataNodePipeMessages..., type)` â 1 site (line 628) | `java.lang.String#format(String, Object...)` | No â JDK |
| 10 | `new UnSupportedDataTypeException(String.format(...))` â 1 site (line 627) | `org.apache.tsfile.write.UnSupportedDataTypeException#<init>(String)` | No â tsfile external dep |

Non-call identifier references (field reads, listed for completeness, not function calls): `Binary.EMPTY_VALUE` (tsfile static field, line 618), `EMPTY_LOCALDATE` (private static field of this same class, defined line 65, used lines 512/526), `DataNodePipeMessages.PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` (in-repo static field, `iotdb-core/datanode/src/main/i18n/en/.../DataNodePipeMessages.java` line 2277).

## Settled answer to the disagreement

**Exactly one** function called by this routine is defined inside this repository: `isNullValue(BitMap, int)` at line 683 of the same file.

**Everything else the routine reaches is an exclusion** â it resolves to either the JDK (`List#size`, `List#get`, `Objects#isNull`, `String#format`) or to the external Apache TsFile dependency (`BitMap#mark`, `DateUtils#parseIntToLocalDate`, `Binary#getValues`, `Binary` constructor, `UnSupportedDataTypeException` constructor), whose sources are not in this tree (confirmed: `iotdb-core/datanode/pom.xml` lines 53â60 declare `org.apache.tsfile:tsfile:${tsfile.version}` as an external artifact, and no `org.apache.tsfile` sources exist under this repo).

No other ingestion-side value-column routine exists in the tree: a repo-wide scan for `valueColumn`/`ValueColumn` method definitions outside the query engine (`calc-commons`) and outside tests returns only `PipeRow`/`PipeResetTabletRow` (field holders), `LastQueryUtil`, `TVColumns`, `TsFileSplitter`, `AlignedTVList`, `InputLocation` â none of which process the value columns of an incoming insert batch the way this parser does.

Completed the dependency inventory review of the ingestion-side value-column routine.

**Routine identified:** `TabletInsertionEventParser.filterValueColumnsByRowIndexList` (lines 473â632 of `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`). It is the routine that handles the value columns of an incoming batch â invoked from `parse(InsertRowNode)` (line 180) and `parse(InsertTabletNode)` (line 274).

**Complete direct-call inventory (10 distinct callables):**
- `isNullValue(BitMap, int)` â 8 sites â defined in this repo, same file line 683 â **the ONLY in-repo function called**
- `rowIndexList.size()` â 15 sites â JDK
- `rowIndexList.get(int)` â 18 sites â JDK
- `nullValueColumnBitmap.mark(int)` â 8 sites â tsfile external
- `Objects.isNull(Object)` â 2 sites â JDK
- `DateUtils.parseIntToLocalDate(int)` â 1 site â tsfile external
- `Binary.getValues()` â 2 sites â tsfile external
- `new Binary(byte[])` â 1 site â tsfile external
- `String.format(...)` â 1 site â JDK
- `new UnSupportedDataTypeException(String)` â 1 site â tsfile external

**Exclusions (cannot be justified against this repo's source):** all JDK and tsfile calls above â they resolve outside the tree (`org.apache.tsfile:tsfile` is a declared external dependency in `iotdb-core/datanode/pom.xml`, lines 53â60).

The two earlier attempts are thereby settled: any inventory claiming more than one in-repo callee, or fewer than the ten listed callables, disagrees with the source.