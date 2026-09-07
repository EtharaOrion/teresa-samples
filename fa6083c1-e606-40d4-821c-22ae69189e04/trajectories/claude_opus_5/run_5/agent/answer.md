I'm checking whether integration-test, which only declares tsfile, actually uses DateUtils alongside common-attributed classes like Binary, BitMap, and TSDataType — but since analyze is skipped there, this doesn't give a clean signal either way.

Meanwhile udf-api, declaring only common with active failOnWarning, gives strong confirmation that TSDataType, Binary, BitMap, Column, and ColumnBuilder live in common. For DateUtils specifically, no module isolates common alone while using it, so I conclude it's genuinely undecidable from this evidence — placing it in either common or tsfile wouldn't break anything given how the dependencies chain together.

I also confirm iotdb-api has no parent dependencies, and the exclusion pattern in cli/service-rpc (excluding all transitives from tsfile, then re-adding common explicitly) supports that common is indeed a transitive dependency of tsfile. Now I'm ready to compile the final identifier inventory from lines 473-631, filtering out Java keywords and classifying each of the roughly 71 tokens by module origin.

Sorting local variables (type, originValueColumn, rowIndexList, and similar parameters) as not requiring attribution, then tracking in-repo references like filterValueColumnsByRowIndexList, isNullValue, EMPTY_LOCALDATE, and DataNodePipeMessages back to their source locations.

I'm also cataloging JDK types (Object, List, Integer, LocalDate, String, primitives) and external tsfile dependencies (TSDataType and its enum constants, BitMap, Binary, DateUtils, UnSupportedDataTypeException) to distinguish which methods like size, get, mark, and parseIntToLocalDate come from external libraries versus the local codebase.
I have everything I need. Final verification confirms the checkout is untouched (`git status --porcelain` empty, `git diff --stat` empty).

# Dependency inventory: `filterValueColumnsByRowIndexList`

## 0. Ground rules I applied

The reviewer asked for this settled **against source**, at **identifier granularity**, **paired with the `dependencies.json` entry**, and with **everything I cannot justify from source recorded as an explicit exclusion**. So: every entry below cites a file and line I actually read; anything I could only infer is in the Exclusions section, not the inventory. The inventory is complete for the routine — I tokenised the body and accounted for all 71 distinct identifiers.

No files were changed. `git status --porcelain` and `git diff --stat` are both empty.

## 1. Identifying the routine

"Ingestion side, handles value columns of an incoming batch" resolves to exactly one method:

`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/pipe/event/common/tablet/parser/TabletInsertionEventParser.java`, **lines 473–631**

```java
private static Object filterValueColumnsByRowIndexList(
    final TSDataType type,
    final Object originValueColumn,
    final List<Integer> rowIndexList,
    final boolean isSingleOriginValueColumn,
    final BitMap originNullValueColumnBitmap,
    final BitMap nullValueColumnBitmap ) {
```

This is the only match in the pipe-ingestion and write-plan-node trees (`grep -rn "private.*\(Object\|void\|Column\).*[Vv]alue[Cc]olumn" .../db/pipe .../plan/node/write` → one hit). Three call sites, all in the same file: **line 182** (`InsertRowNode` path, `isSingleOriginValueColumn=true`, origin bitmap `null`), **line 275** and **line 371** (tablet / batch paths, `false`, `getBitMap(originBitMapList, i)`).

## 2. Inventory — identifiers requiring an external attribution

Coordinates are quoted exactly as they appear in `dependencies.json` (158 entries; both `org.apache.tsfile:common` and `org.apache.tsfile:tsfile` are present). `iotdb-core/datanode/pom.xml` lines 52–61 declares both explicitly at `${tsfile.version}` = `2.3.2-260616-SNAPSHOT` (root `pom.xml:148`).

| Identifier (as written) | Lines in routine | Import | Attributed to | Justification |
|---|---|---|---|---|
| `TSDataType` (param type, l.474) plus enum constants `INT32` `DATE` `INT64` `TIMESTAMP` `FLOAT` `DOUBLE` `BOOLEAN` `TEXT` `BLOB` `STRING` | 474, 481, 498, 536–537, 558, 573, 588, 605–607 | `org.apache.tsfile.enums.TSDataType` (l.36) | **`org.apache.tsfile:common`** | see §3 |
| `BitMap` (two params) | 478, 479 | `org.apache.tsfile.utils.BitMap` (l.40) | **`org.apache.tsfile:common`** | see §3 |
| `Binary`, `Binary.EMPTY_VALUE`, `new Binary(...)` | 609, 611, 612, 613, 618, 621 | `org.apache.tsfile.utils.Binary` (l.39) | **`org.apache.tsfile:common`** | see §3 |
| `UnSupportedDataTypeException` | 627 | `org.apache.tsfile.write.UnSupportedDataTypeException` (l.42) | **`org.apache.tsfile:common`** | see §3 |
| `DateUtils`, `.parseIntToLocalDate` | 530 | `org.apache.tsfile.utils.DateUtils` (l.41) | **EXCLUSION — see §4.1** | not justifiable from this checkout |
| `.mark(int)` (member of `BitMap`) | 491, 513, 527, 547, 564, 581, 598, 619 | — | **EXCLUSION — see §4.2** | member granularity not established |
| `.getValues()` (member of `Binary`) | 616, 621 | — | **EXCLUSION — see §4.2** | member granularity not established |

## 3. The justification for the four `common` attributions

This is the point the two earlier attempts disagreed on, and it is decidable from source.

`iotdb-api/udf-api/pom.xml` has exactly **one** dependency:

```xml
<dependencies>
    <dependency>
        <groupId>org.apache.tsfile</groupId>
        <artifactId>common</artifactId>
        <version>${tsfile.version}</version>
    </dependency>
</dependencies>
```

Its parent `iotdb-api/pom.xml` declares no dependencies at all, and contains no `maven-dependency-plugin` configuration. Yet `udf-api` sources compile against `org.apache.tsfile.enums.TSDataType` (`utils/RowImpl.java:27`), `org.apache.tsfile.utils.Binary` (`relational/access/Record.java:24`, `type/Type.java:24`, `relational/table/argument/ScalarArgument.java:25`, `utils/ResultValue.java:23`) and `org.apache.tsfile.utils.BitMap` (`UDAF.java:27`, used at `UDAF.java:44` in the signature `void addInput(State state, Column[] columns, BitMap bitMap)`).

`UnSupportedDataTypeException` is pinned the same way one hop out: `example/udf/pom.xml` depends only on `slf4j-api` and on `udf-api` (scope `provided`) — so `common` is its only route to any tsfile class — and `example/udf/src/main/java/org/apache/iotdb/udf/UDAFExample.java:33` imports `org.apache.tsfile.write.UnSupportedDataTypeException`, throwing it at line 118.

Why this is binding rather than incidental: root `pom.xml` lines 1194–1209 binds `maven-dependency-plugin:analyze-only` to `verify` with `<failOnWarning>true</failOnWarning>`, and the comment above it (lines 1186–1193) states the intent — "make sure everything directly required is also directly added as a dependency". `udf-api` does not opt out; only `example/pom.xml` (lines 58–71) and `integration-test/pom.xml` (lines 396–410) set `<skip>true</skip>`. So a build of `udf-api` would fail with "Used undeclared dependency: org.apache.tsfile:tsfile" if any of these four classes actually lived in `tsfile`.

Corroborating evidence that `common` is a transitive of `tsfile` (which is what makes the *other* modules' usage consistent): `iotdb-client/service-rpc/pom.xml` declares `tsfile` with `<exclusion><groupId>*</groupId><artifactId>*</artifactId></exclusion>` "we want to reduce the size of JDBC" **and separately re-declares `common`** — i.e. it strips all transitives of `tsfile` and adds `common` back by hand. Likewise `integration-test/pom.xml` declares only `tsfile` yet uses `Binary`, `BitMap`, `TSDataType`, `DateUtils` and `UnSupportedDataTypeException`; that only compiles if `tsfile` drags `common` in, and it does not trip the analyzer because `integration-test` skips it.

**Adjudicating the two earlier attempts:** the one that assigned the whole routine to `org.apache.tsfile:tsfile` is wrong — `udf-api` and `example/udf` disprove it for four of the five classes. The one that assigned everything to `org.apache.tsfile:common` is right on four and unjustified on `DateUtils`.

## 4. Exclusions (audited, cannot be justified against source)

**4.1 `DateUtils` / `DateUtils.parseIntToLocalDate` (line 530).** Undecidable here. I enumerated every module importing `org.apache.tsfile.utils.DateUtils`: `external-service-impl/rest`, `integration-test`, `iotdb-client/{cli,jdbc,service-rpc,session,subscription}`, `iotdb-core/{calc-commons,datanode,node-commons}`. Every one of them declares **both** `tsfile` and `common` (except `integration-test`, which declares only `tsfile` and has the analyzer skipped). Conversely, none of the three `common`-only modules (`iotdb-api/udf-api`, `library-udf`, `example/pipe-count-point-processor`) uses `DateUtils` — I checked, zero files. So there is no module whose POM discriminates the two artifacts for this class, and both hypotheses are consistent with every POM in the tree. Note this is not a symmetric coin-flip artefact: it is *specifically* the `DATE` branch that is unusual — lines 498–534 are the only branch that type-tests the incoming payload (`originValueColumn instanceof LocalDate` / `instanceof LocalDate[]`) and falls back to `int[]` + `parseIntToLocalDate`; every other branch is a straight cast. `DateUtils` is used by no other branch, so it is the one class the routine reaches that nothing else in the routine corroborates.

**4.2 Member-level attribution: `BitMap.mark(int)` (8 sites) and `Binary.EMPTY_VALUE` / `Binary.getValues()`.** The reviewer asked for identifier granularity, and I can pin the *declaring classes* to `common` per §3, but not the individual members, because no `common`-only module exercises them: `grep -rn "\.mark(\|\.markAll("` across `udf-api`, `library-udf` and `example/udf` returns nothing, and `Binary.EMPTY_VALUE` occurs only in `iotdb-core/datanode` (33×) and `iotdb-client/session` (5×) — both of which declare both artifacts. `getValues()` *is* exercised in `udf-api` (`RowImpl.java:125`, `ScalarArgument.java:80,120`), so if member granularity is wanted, `getValues` alone can be moved out of this exclusion and into the inventory as `common`.

**4.3 What would settle 4.1 and 4.2.** Nothing in-repo can. There is no vendored tsfile source (`grep -rn "^package org.apache.tsfile"` returns nothing), no artifact cache (`~/.m2` does not exist; `find / -name "tsfile*.jar"` is empty), and `2.3.2-260616-SNAPSHOT` is an unpublished snapshot. Resolving it needs either the two jars, or a `mvn dependency:analyze` / `dependency:tree` run against a populated repository — neither of which I can do read-only and offline. There is also no generated SBOM to fall back on: `src/main/groovy/checkDependencies.groovy` compares `dependencies.json` against `target/apache-${artifactId}-${version}-sbom.transformed.json`, produced by the `enable-sbom-check` profile (root `pom.xml` 1643–1732) via `src/main/xslt/sbom-filter.xsl`; no `target/` output exists in this checkout.

## 5. Remainder of the inventory (complete, for closure)

**In-repo symbols (no external attribution).** `filterValueColumnsByRowIndexList` (self, l.473); `isNullValue` → same file l.683, `return Objects.nonNull(bitMap) && bitMap.isMarked(rowIndex);`, called at 489, 511, 525, 545, 562, 579, 596, 617; `EMPTY_LOCALDATE` (used 512, 526) → same file l.65, `private static final LocalDate EMPTY_LOCALDATE = LocalDate.of(1000, 1, 1);`; `DataNodePipeMessages` (import l.26) and its constant `PIPE_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_5D5C02E4` (l.629) → **two** in-repo sources selected at build time by `${i18n.locale}` via `build-helper-maven-plugin`: `iotdb-core/datanode/src/main/i18n/en/.../DataNodePipeMessages.java:2277` (`"Data type %s is not supported."`) and `.../i18n/zh/...:2115` (`"不支持数据类型 %s。"`). Both are one-format-specifier templates and agree, so the `zh` build is unaffected.

**JDK symbols (correctly absent from `dependencies.json`, which per `sbom-filter.xsl` lists only non-`org.apache.iotdb` SBOM components).** `Object`, `List`, `Integer`, `.size()`, `.get(int)`, `LocalDate`, `Objects`, `.isNull`, `String`, `.format`.

**Language tokens / locals (nothing to attribute).** Keywords and primitives `case default else false final for if instanceof new private return static switch throw boolean int long float double`; the `D`/`F`/`L` tokens my scan picked up are numeric literal suffixes in `0D`, `0F`, `0L`, not identifiers; locals and parameters `type`, `originValueColumn`, `rowIndexList`, `isSingleOriginValueColumn`, `originNullValueColumnBitmap`, `nullValueColumnBitmap`, `i`, `valueColumns`, `intValueColumns`, `dateValueColumns`, `longValueColumns`, `floatValueColumns`, `doubleValueColumns`, `booleanValueColumns`, `binaryValueColumns`.

## 6. Two incidental observations (reported, not acted on)

Both are cosmetic and outside the inventory's scope; I mention them only because they sit inside the audited range and a reviewer reading the same lines will notice them.

- Line 479 reads `final BitMap nullValueColumnBitmap ) {` — a stray space before the closing paren, which `mvn spotless:apply` would normalise.
- Lines 500, 504 and 687 carry trailing-whitespace-only content inside otherwise blank lines.

I did not touch either, since the task is a read-only inventory review and formatting is not an inventory finding.