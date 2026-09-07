# Ground truth — fa6083c1-e606-40d4-821c-22ae69189e04

`apache/iotdb` @ `8e5e8502d62f3a8310275a242eb39f42f82877ae`
Family: `dependency_search`
PR context: [#18248](https://github.com/apache/iotdb/pull/18248) (merge
`e5651cbc928f3449319dc588f54cb189d9c4a7e7`, single parent; I2 PURE — 7 files, +895/-28 both
locally and per the GitHub API) touches this class. The gold localizes behaviour already present
at `base_commit`; this family does not require a fix/after state.

Provenance note: `base_commit` `8e5e8502` is the **merge parent of PR #18248** — `e5651cbc^`,
verified with `git rev-list --parents -n1 e5651cbc` — so the tree the solver sees is exactly the
pre-merge state. Its subject is "Fix flaky concurrent queue and WAL tests (#18246)".

## Gold

`iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/TabletDecoder.java`
:: `decodeValues` — lines 124-140.

## The direct in-repository call surface

Six calls, reaching **two** files in one module (`iotdb-core/datanode`):

| # | callee | declared in |
|---|---|---|
| 1 | `uncompress` (private, same class) | `TabletDecoder.java:86` |
| 2 | `RPCServiceThriftHandlerMetrics.getInstance()` — invoked **three times** (127, 129, 137) | `.../db/protocol/thrift/handler/RPCServiceThriftHandlerMetrics.java` |
| 3 | `recordUnCompressionSizeTimer` | same metrics class |
| 4 | `recordCompressionSizeTimer` | same metrics class |
| 5 | `recordDecodeLatencyTimer` | same metrics class |
| 6 | `decodeColumn` (private, same class) — invoked once per value column, from the loop at line 134 | `TabletDecoder.java:142` |

## The exclusion that carries the task

Every remaining call in the body belongs to **`org.apache.tsfile`**, which is *not this
repository*. It is a separate Apache project consumed as a dependency, and no source for it
exists anywhere in this tree. The package prefix `org.apache.tsfile` sits directly alongside
`org.apache.iotdb` in the import block, and the types are the domain's core vocabulary, which is
what makes the mistake natural:

```java
import org.apache.tsfile.compress.IUnCompressor;
import org.apache.tsfile.encoding.decoder.Decoder;
import org.apache.tsfile.enums.TSDataType;
import org.apache.tsfile.file.metadata.enums.CompressionType;
import org.apache.tsfile.file.metadata.enums.TSEncoding;
import org.apache.tsfile.utils.Binary;
import org.apache.tsfile.utils.Pair;
import org.apache.tsfile.utils.ReadWriteIOUtils;
```

So `new Pair<>(columns, uncompressed)` on the return line is **external**, as are
`Decoder.getDecoderByType` and `IUnCompressor.uncompress` reached further down.

The exclusion that is easiest to get wrong sits one frame down. `uncompress` itself calls
`RPCServiceThriftHandlerMetrics.getInstance().recordDecompressLatencyTimer(...)` at
`TabletDecoder.java:101-102`. That recorder is in this repository, on the same metrics class, reached
through the same accessor and declared in the same file as the other three, but `decodeValues` never
calls it: it is reached only by way of `uncompress`, so it is an indirect call and does not belong on
the list.

**The hardest exclusion**, and the one the prompt's "a reason attached to each" is aimed at:
`recordDecompressLatencyTimer` (`TabletDecoder.java:102`). It is on the *same metrics class*,
reached through the *same accessor*, in the *same file* — but it is called inside the private
`uncompress`, one frame below `decodeValues`, so it is indirect and does not belong on the list.

Other exclusions: `buffer.remaining()` and `ByteBuffer` operations (JDK), `System.nanoTime()`
(JDK, twice), and the `new Object[dataTypes.length]` allocation, which is not a call.

## The neighbouring routine, and why it is the likely wrong answer

`decodeTime` (lines 65-84) is the public twin. It does almost the same job for the other part of
the batch and its callee set overlaps heavily but is **not** the same:

| callee | `decodeValues` | `decodeTime` |
|---|---|---|
| `uncompress` | yes | yes |
| `getInstance()` | 3× | 4× |
| `recordUnCompressionSizeTimer` | yes | yes |
| `recordCompressionSizeTimer` | yes | yes |
| `recordDecodeLatencyTimer` | yes | yes |
| **`recordMemoryUsage`** | **no** | **yes** (line 77) |
| **`decodeColumn`** | **yes** (142) | no |
| **`decodeColumnForTimeStamp`** | no | **yes** — called at 80, declared at 112 |

Answering for the twin therefore yields five of six correct and two wrong, which no amount of
name matching resolves. Stated as exclusions from the audited routine's list:
**`recordMemoryUsage` is not called by `decodeValues`** — it belongs to the twin, at line 77 —
and **`decodeColumnForTimeStamp` is not called by `decodeValues`** either; the twin calls it at
line 80 where this routine calls `decodeColumn`. The metrics accessor is invoked **three** times
here against **four** in the twin.

## A convention worth noting

`decodeColumnForTimeStamp` reads `columnEncodings.get(0)` while `decodeColumn` reads
`columnEncodings.get(columnIndex + 1)`. The offset is deliberate and consistent: slot 0 of the
encoding list belongs to the time column and value column *i* lives at *i + 1*. It is not a
defect, and it is the reason the two decode helpers cannot be interchanged.

## Gold answer

```json <!-- gold -->
{
  "file": "iotdb-core/datanode/src/main/java/org/apache/iotdb/db/utils/TabletDecoder.java",
  "function": "decodeValues",
  "explanation": "decodeValues in TabletDecoder.java, lines 124-140, makes six calls to functions defined inside this repository, reaching two files in the iotdb-core/datanode module. From its own class it calls the private uncompress at line 86 and the private decodeColumn declared at line 142, which it invokes once per value column from the loop at line 134. From org.apache.iotdb.db.protocol.thrift.handler.RPCServiceThriftHandlerMetrics it calls the static getInstance three times, at lines 127, 129 and 137, and through it recordUnCompressionSizeTimer declared at RPCServiceThriftHandlerMetrics.java:51, recordCompressionSizeTimer at :55 and recordDecodeLatencyTimer at :59, with the static getInstance declared at :173, the accessor being invoked three times here where the twin invokes it four. Excluded from this routine's list are recordMemoryUsage, which the twin calls at line 77 and this routine does not call at all, and decodeColumnForTimeStamp, which the twin calls at line 80 in place of decodeColumn. Excluded as indirect is recordDecompressLatencyTimer at line 102, which sits on the same metrics class and is reached through the same accessor but from inside the private uncompress, one frame below this routine. Everything else in the body belongs to org.apache.tsfile, which is a separate Apache project consumed as a dependency and has no source anywhere in this tree, so new Pair on the return line is external, as are Decoder.getDecoderByType and IUnCompressor.uncompress reached further down; the package prefix sits immediately beside org.apache.iotdb in the import block, which is what makes that mistake natural. Also excluded are buffer.remaining and the other ByteBuffer operations and System.nanoTime twice, all of which are JDK standard library calls and not code this repository declares, and the new Object array allocation, which is a construction and not a call. The neighbouring public twin decodeTime at lines 65-84 does almost the same job for the timestamp column and shares uncompress and all three timer recorders, but it additionally calls recordMemoryUsage at line 77 and calls decodeColumnForTimeStamp, declared at line 112, from line 80 in place of decodeColumn, and it invokes getInstance four times rather than three, so attributing its set to decodeValues yields two wrong entries. The two decode helpers are not interchangeable because decodeColumnForTimeStamp reads columnEncodings.get(0) while decodeColumn reads columnEncodings.get(columnIndex + 1), the encoding list reserving slot 0 for the time column."
}
```
