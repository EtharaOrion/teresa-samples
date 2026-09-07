I settled the inventory against the source itself. Below is the audit for the ingestion‑side routine that handles the value columns of an incoming batch, with every identifier it reaches quoted, paired with the declaration I could verify, and every unverifiable one written up as an explicit exclusion. I made no edits — this checkout is untouched.

## 1. Which routine this is

`org.apache.iotdb.db.utils.QueryDataSetUtils#readTabletValuesFromBuffer(ByteBuffer, TSDataType[], int, int)`
File: `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/QueryDataSetUtils.java`, lines **622–687** (annotation line 622, signature 623–624, body 625–687).

Verbatim signature:

```java
@SuppressWarnings("squid:S3776")
  public static Object[] readTabletValuesFromBuffer(
      ByteBuffer buffer, TSDataType[] types, int columns, int size) {
```

This is the one the two earlier attempts most plausibly disagreed about, because there are **two** same‑named overloads in the same file:

* line **604** `readTabletValuesFromBuffer(ByteBuffer buffer, List<Integer> types, int columns, int size)` — a thin adapter that converts `List<Integer>` → `TSDataType[]` via `TSDataType.values()[types.get(i)]` (line 608) and delegates at line 610;
* line **623** — the real value‑column decoder.

They are separated by blank lines 612–621 (verified with `cat -A`: nine genuinely empty lines, no stripped comment text remains), which is the likely reason one reviewer attributed the body to the `List<Integer>` overload. The delegating overload at 604 is *not* the routine under audit; it is a caller of it.

Its ingestion call sites (the "paired with" side):

* `iotdb-core/datanode/.../plan/parser/StatementGenerator.java:412` — `insertTabletStatement.setColumns(QueryDataSetUtils.readTabletValuesFromBuffer(req.valuesList.get(i), req.typesList.get(i), req.measurementsList.get(i).size(), req.sizeList.get(i)))` → hits the **604** overload (`List<Integer>` types), which delegates.
* `iotdb-core/datanode/.../plan/node/write/InsertTabletNode.java:860` (`subDeserialize`) and `:1279` (WAL deserialization) — both `QueryDataSetUtils.readTabletValuesFromBuffer(buffer, dataTypes, measurementSize, rowCount)` → hit the **623** overload directly.

## 2. Inventory — identifiers reached, justified against source in this checkout

| Identifier as written | Kind | Verified declaration |
|---|---|---|
| `readTabletValuesFromBuffer` | method under audit | `QueryDataSetUtils.java:623` |
| `buffer`, `types`, `columns`, `size` | parameters | `QueryDataSetUtils.java:624` |
| `values` | local `Object[]` | `:625` (`Object[] values = new Object[columns];`) |
| `i` | loop var | `:626` |
| `index` | loop var (re‑declared per case block) | `:630`, and the corresponding loops in each case |
| `boolValues` | local | `:629` (`boolean[] boolValues = new boolean[size];`) |
| `intValues` | local | `:637` |
| `longValues` | local | `:645` |
| `floatValues` | local | `:652` |
| `doubleValues` | local | `:659` |
| `binaryValues` | local | `:668` (`Binary[] binaryValues = new Binary[size];`) |
| `binarySize` | local | `:671` (`int binarySize = buffer.getInt();`) |
| `binaryValue` | local | `:672` (`byte[] binaryValue = new byte[binarySize];`) |
| `DataNodeMiscMessages` | class | **in repo but not under `src/main/java`**: `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodeMiscMessages.java:23` (`public final class DataNodeMiscMessages`); imported at `QueryDataSetUtils.java:23` |
| `MISC_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC` | constant, used at `:681–682` | `…/i18n/en/…/DataNodeMiscMessages.java:1343` = `"data type %s is not supported when convert data at client"`; zh twin at `…/i18n/zh/…/DataNodeMiscMessages.java:1325` = `"客户端转换数据时不支持数据类型 %s"` |

The `DataNodeMiscMessages` entry is the second thing an auditor can legitimately get wrong: `ls iotdb-core/datanode/src/main/java/org/apache/iotdb/db/i18n/` fails (exit 2) — the package exists only under `src/main/i18n/<locale>/`, and is grafted onto the compile roots by `build-helper-maven-plugin` (`iotdb-core/datanode/pom.xml:447`, source `${project.basedir}/src/main/i18n/${i18n.locale}` at `:458`; `<i18n.locale>en</i18n.locale>` at root `pom.xml:149`, overridden to `zh` at `pom.xml:1988`). So it *is* justifiable against source — just not where a naive `src/main/java` walk looks. It should be an inventory entry, not an exclusion.

## 3. Exclusions — reached, but not justifiable against source in this checkout

Every one of these is reached by the routine; none of their sources are present here, so each is recorded as an exclusion rather than an inventory entry.

**A. tsfile artifacts** — declared deps `org.apache.tsfile:common` and `org.apache.tsfile:tsfile` at `iotdb-core/datanode/pom.xml:53–61`, version `${tsfile.version}` = `2.3.2-260616-SNAPSHOT` (root `pom.xml:148`). Both coordinates are present in `dependencies.json` (which lists 158 entries, the only two matching `tsfile`/`iotdb` being `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`). No sources, no jars: `find / -name "tsfile*.jar"` returns nothing and `~/.m2/repository/org/apache/tsfile` does not exist, so the members below cannot be checked against source, only against the import lines.

* `TSDataType` — import `QueryDataSetUtils.java:30` (`org.apache.tsfile.enums.TSDataType`); used as the parameter type and as the switch selector `types[i]` at `:627`. Also `TSDataType.values()` in the sibling overload at `:608`.
* The enum constants reached in the switch: `BOOLEAN` (628), `INT32` (635), `DATE` (636), `INT64` (643), `TIMESTAMP` (644), `FLOAT` (651), `DOUBLE` (658), `TEXT` (665), `BLOB` (666), `STRING` (667), `OBJECT` (668). Exhaustiveness is unverifiable for the same reason; anything not in this set falls to `default` (678).
* `BytesUtils` / `BytesUtils.byteToBool` — import `:34` (`org.apache.tsfile.utils.BytesUtils`), call at `:631`.
* `Binary` / `new Binary(byte[])` — import `:32` (`org.apache.tsfile.utils.Binary`), used at `:668` and `:674`. Note the repo *does* contain two unrelated `Binary.java` files (`iotdb-api/pipe-api/.../pipe/api/type/Binary.java`, `iotdb-api/udf-api/.../udf/api/type/Binary.java`); neither is the imported type, and treating either as the source of truth would be a false inventory entry.
* `UnSupportedDataTypeException` — import `:37` (`org.apache.tsfile.write.UnSupportedDataTypeException`), thrown at `:679`.

**B. JDK identifiers** — no coordinate in `dependencies.json`, no source in the checkout.

* `java.nio.ByteBuffer` (import `:42`) and the methods reached on it: `get()` (631), `getInt()` (639, 671), `getLong()` (647), `getFloat()` (654), `getDouble()` (661), `get(byte[])` (673).
* `java.lang.Object` (`Object[] values`), `java.lang.String.format` (680), `java.lang.SuppressWarnings` (622, argument `"squid:S3776"` — a SonarQube cognitive‑complexity suppression, not a Java construct).
* For the delegating overload only: `java.util.List` (import `:44`) and `List.get`/`List.size`.

## 4. Notes the reviewer should carry into the write‑up

* The audit is complete only at the granularity of *declaration site*, not *behaviour*: for every tsfile and JDK symbol above I can quote the import line but cannot quote a declaration, so their semantics (e.g. `byteToBool`'s truthiness rule, `Binary`'s copy‑vs‑alias of the `byte[]`) are asserted nowhere in this repository.
* One thing visible purely from source and worth recording: the loop bound is `columns` (`:626`) while the type array is indexed as `types[i]` (`:627`), so the routine trusts callers to pass `columns <= types.length`. All three call sites pass the measurement count for both, but that invariant lives in the callers, not here.
* `size` drives every allocation (`new boolean[size]`, `new int[size]`, …) and `binarySize` is read straight from the buffer at `:671` and used as an allocation length at `:672` with no bound check — an observation about the routine, not a change I have made or am recommending here.

I now have the full dependency inventory for the routine at declaration-site granularity, with exclusions noted, and I need to resolve which overload the two earlier attempts disagreed on. I'm also double-checking that the enum constants referenced match the TSDataType set.

## What the routine is (this is the disagreement, settled against source)

The "ingestion-side routine that handles the value columns of an incoming batch" is:

`org.apache.iotdb.db.utils.QueryDataSetUtils#readTabletValuesFromBuffer(ByteBuffer, TSDataType[], int, int)`
file `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/QueryDataSetUtils.java`, **lines 622–687** (annotation 622, signature 623–624, body 625–687).

Why the two earlier attempts disagreed: there are **two same-named overloads in the same file**, separated by a block of blank lines (612–621, confirmed with `cat -A`):

- line 604 — `readTabletValuesFromBuffer(ByteBuffer buffer, List<Integer> types, int columns, int size)`. A thin adapter: it maps `List<Integer>` → `TSDataType[]` via `TSDataType.values()[types.get(i)]` (line 608) and delegates on line 610. It decodes nothing itself.
- line 623 — the actual value-column decoder.

Both are reachable from ingestion, which is why each attempt could point at a different one:
- `queryengine/plan/parser/StatementGenerator.java:412` (Thrift `TSInsertTabletsReq` path, `req.valuesList` / `req.typesList`) calls the **604** overload, which delegates to 623.
- `queryengine/plan/planner/plan/node/write/InsertTabletNode.java:860` (`subDeserialize`) and `:1279` (WAL/second deserialize path) call the **623** overload directly with a `TSDataType[]`.

So 604 is a caller/adapter, not the routine; the audited entry is 623. Those three call sites plus the internal one at 610 are the complete set of references (`grep` over `--include=*.java` for `readTabletValuesFromBuffer` returns exactly lines 412, 860, 1279, 604, 610, 623).

## Dependency inventory for lines 622–687, paired with the import that declares each identifier

Every identifier the routine reaches, quoted, with the source line I can justify it from:

| Identifier | Use site(s) in 622–687 | Declaration justified by |
|---|---|---|
| `ByteBuffer` (+ `get()`, `getInt()`, `getLong()`, `getFloat()`, `getDouble()`, `get(byte[])`) | 624; 631, 639, 647, 654, 661, 671, 673 | `import java.nio.ByteBuffer;` — line 42 |
| `TSDataType` (param type; enum constants `BOOLEAN` 628, `INT32` 635, `DATE` 636, `INT64` 643, `TIMESTAMP` 644, `FLOAT` 651, `DOUBLE` 658, `TEXT` 665, `BLOB` 666, `STRING` 667, `OBJECT` 668) | 624, 627–668, 683 | `import org.apache.tsfile.enums.TSDataType;` — line 30 |
| `BytesUtils.byteToBool` | 631 | `import org.apache.tsfile.utils.BytesUtils;` — line 34 |
| `Binary` (array type + `new Binary(byte[])`) | 669, 674 | `import org.apache.tsfile.utils.Binary;` — line 32 |
| `UnSupportedDataTypeException` | 679 | `import org.apache.tsfile.write.UnSupportedDataTypeException;` — line 37 |
| `DataNodeMiscMessages.MISC_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC` | 681–682 | `import org.apache.iotdb.db.i18n.DataNodeMiscMessages;` — line 23 |
| `String.format` | 680 | `java.lang`, implicit |
| `Object` (`Object[] values`, return type) | 623, 625 | `java.lang`, implicit |
| `SuppressWarnings` (argument `"squid:S3776"`) | 622 | `java.lang`, implicit; the argument is a SonarQube cognitive-complexity rule id, not a Java construct |

Primitive array types (`boolean[]` 629, `int[]` 637, `long[]` 645, `float[]` 652, `double[]` 659, `byte[]` 672) are language constructs, not dependencies.

`java.util.List` (`import` line 44) is reached only by the **604** adapter (`types.size()`, `types.get(i)`), never by 623. If the inventory entry is scoped to 623 as settled above, `List` does not belong in it.

Where the two non-JDK families resolve at artifact level: `org.apache.tsfile.*` is an external artifact — `dependencies.json` lists `org.apache.tsfile:common` and `org.apache.tsfile:tsfile`, and `iotdb-core/datanode/pom.xml:53–61` declares both at `${tsfile.version}` = `2.3.2-260616-SNAPSHOT` (root `pom.xml:148`).

## Exclusions — entries I cannot justify against source in this checkout

1. **All `org.apache.tsfile` declaration sites.** `find . -name TSDataType.java -o -name Binary.java -o -name BytesUtils.java -o -name UnSupportedDataTypeException.java` finds none of them in this repo (the only `Binary.java` hits are the unrelated `org.apache.iotdb.pipe.api.type.Binary` and `org.apache.iotdb.udf.api.type.Binary`), and there is no local jar: `~/.m2/repository/org/apache/tsfile` does not exist and `find / -name "tsfile*.jar"` returns nothing. I can quote the import line and the pom coordinates; I **cannot** quote a declaration. Consequently I also cannot certify *which* of the two artifacts (`common` vs `tsfile`) declares each symbol, nor any behavioural detail (e.g. `BytesUtils.byteToBool`'s truthiness rule, whether `new Binary(byte[])` copies or aliases the array). These are excluded as unverifiable here; resolving them needs the tsfile sources or jars for `2.3.2-260616-SNAPSHOT`.

2. **A naive "walk `src/main/java`" inventory would wrongly exclude `DataNodeMiscMessages`.** `ls iotdb-core/datanode/src/main/java/org/apache/iotdb/db/i18n/` fails (exit 2) — that package does not exist under `src/main/java`. The class lives at `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodeMiscMessages.java` (declared `public final class` at line 23; the constant at line 1343 = `"data type %s is not supported when convert data at client"`) with a locale twin at `src/main/i18n/zh/.../DataNodeMiscMessages.java:1325` = `"客户端转换数据时不支持数据类型 %s"`. The directory is grafted onto the compile source roots by `build-helper-maven-plugin` (`iotdb-core/datanode/pom.xml:447`, source `${project.basedir}/src/main/i18n/${i18n.locale}`), with `<i18n.locale>en</i18n.locale>` at root `pom.xml:149` and an override to `zh` at `pom.xml:1988`. So this entry **is** justifiable against source and must stay in the inventory; only its path is non-obvious.

3. **Nothing else.** No reflection, no service loading, no static initialiser outside the file, and no static state read inside 622–687 — the two file-level statics (`TSFILE_CONFIG`, `MAX_RETURN_SIZE`) are not touched by this routine.

## One thing worth flagging (observation only — I made no change)

The routine indexes `types[i]` for `i` in `[0, columns)` (lines 626–627) without checking `columns <= types.length`, and it trusts `binarySize = buffer.getInt()` (671) as an allocation size for `new byte[binarySize]` (672) with no bound or negativity check. Both `columns` and the buffer contents originate from the client request on the `StatementGenerator:412` path (`req.measurementsList.get(i).size()`, `req.valuesList.get(i)`). I am reporting this as a property of the code, not proposing an edit.

No files were created, modified, or deleted; all inspection was read-only (`grep`, `awk`, `sed -n`, `find`, `git log`).