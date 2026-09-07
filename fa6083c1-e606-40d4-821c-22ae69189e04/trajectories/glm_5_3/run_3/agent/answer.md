Let me finalize. The user's original task (from the compressed first message): they want a dependency inventory of one ingestion-side routine handling value columns of an incoming batch — every identifier it directly calls/reaches, paired with file+line granularity, and exclusions listed. I've identified convertTableColumn. I have all the facts. Let me write the final answer now.
I have all the evidence needed. Let me submit the completed inventory.

**Target routine (settled against source):**

`private Object convertTableColumn(final Object input, final rowCount, TSDataType type)` â `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/queryengine/plan/statement/crud/InsertTabletStatement.java:151`

This is the ingestion-side routine that handles the value columns of an incoming batch: the `InsertTabletStatement(Tablet, boolean, String)` constructor (same file, line 116) iterates the columns of a freshly arrived `Tablet` batch and calls it once per value column at line 136 (`convertTableColumn(tablet.getValues()[i], tablet.getRowSize(), dataTypes[i])`). A repository-wide grep shows exactly one declaration (line 151) and one call site (line 136) for this identifier, so there is no ambiguity about which routine is being inventoried.

**In-repo dependency entries (1)**

| # | Identifier reached | Reached at | Declared at |
|---|---|---|---|
| 1 | `DataNodeQueryMessages.QUERY_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC` | `InsertTabletStatement.java:184-185` (read inside `String.format` feeding the `UnSupportedDataTypeException` throw at line 182) | `iotdb-core/datanode/src/main/i18n/en/org/apache/iotdb/db/i18n/DataNodeQueryMessages.java:2780-2781`, value `"data type %s is not supported when convert data at client"`; zh counterpart `iotdb-core/datanode/src/main/i18n/zh/org/apache/iotdb/db/i18n/DataNodeQueryMessages.java:3316-3318` |

That is the **complete** in-repo list â no other identifier the routine reaches resolves to source inside this repository. Every entry is quoted verbatim above and each can be re-verified by the cited file:line pair, which is the justification standard requested ("no less than truth" â nothing is inferred).

**Exclusions (identifiers reached that are *not* audited in-repo entries)**

The disagreement between the earlier two attempts almost certainly stems from these: they *are* identifiers the routine reaches, but they resolve to the external `tsfile` artifact, not to source in this repository â `org.apache.tsfile:tsfile:2.3.2-260616-SNAPSHOT` (`pom.xml:148`, dependency management at `pom.xml:317-319`; tsfile is a separate repo per `README.md`). `find` over the repo confirms no `org/apache/tsfile/.../DateUtils.java`, `.../Binary.java`, `.../TSDataType.java`, or `.../UnSupportedDataTypeException.java` exists here:

| Identifier (verbatim, as reached) | Reached at (line) | Resolution |
|---|---|---|
| `DateUtils.parseDateExpressionToInt` | 154 | `org.apache.tsfile.utils.DateUtils` (import at `InsertTabletStatement.java:57`) â external |
| `Binary.EMPTY_VALUE` | 159, 179 | `org.apache.tsfile.utils.Binary` (import line 55) â external. Note the in-repo `Binary` classes under `iotdb-api/pipe-api` / `iotdb-api/udf-api` are different types and are *not* the ones bound here |
| `Binary[]::new` | 160 | same external `Binary` |
| `TSDataType` (enum cases `BOOLEAN`â¦`STRING`, and the `%s` argument at line 186) | 162-186 | `org.apache.tsfile.enums.TSDataType` (import line 50) â external |
| `UnSupportedDataTypeException` | 182 | `org.apache.tsfile.write.UnSupportedDataTypeException` (import line 60) â external |
| `Arrays.stream`, `Arrays.fill`, `Objects.nonNull`, `Integer::intValue`, `String.format`, `LocalDate` | 153-156, 158-160, 179, 183 | JDK (`java.util.*`, `java.time.*`) â standard library, not an audited repo entry |

**Why this settles the disagreement:** the routine reaches a total of one repository-owned identifier (the i18n message constant) plus five tsfile/JDK groups. Any prior inventory listing more in-repo entries for this routine was reaching beyond `convertTableColumn` itself (e.g. the constructor's `tablet.getValues()`/`setColumns` chain, or `CommonUtils.createValueColumnOfDataType` at `iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/CommonUtils.java:389`, which is a *different* routine reached only via `swapColumn`/`insertColumn` at lines 686/743, not from `convertTableColumn`); any inventory listing zero was likely treating the i18n constant as configuration rather than source. Both readings are excluded by the granularity the reviewer asked for â direct calls/reaches of the routine only.

Sent the completed dependency inventory. Summary: (1) Target settled as convertTableColumn (InsertTabletStatement.java:151, called once per value column at line 136 from the Tablet-batch constructor at line 116 â one declaration, one call site repo-wide). (2) In-repo audited entries: exactly 1, the i18n constant DataNodeQueryMessages.QUERY_EXCEPTION_DATA_TYPE_S_IS_NOT_SUPPORTED_WHEN_CONVERT_DATA_AT_CLIENT_405429CC (en DataNodeQueryMessages.java:2780-2781, zh 3316-3318), reached at InsertTabletStatement.java:184-185. (3) Exclusions: DateUtils.parseDateExpressionToInt (154), Binary.EMPTY_VALUE / Binary[]::new (159,160,179), TSDataType enum + value (162-186), UnSupportedDataTypeException (182) â all resolve to the external org.apache.tsfile:tsfile:2.3.2-260616-SNAPSHOT artifact (pom.xml:148,317-319), plus JDK-only usage (Arrays/Objects/Integer/String.format/LocalDate) â none have source in this repository. No files were modified; this was read-only analysis.