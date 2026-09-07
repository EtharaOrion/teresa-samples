The user wants me to finish. Let me compose the full, complete final answer in prose, covering all the points asked:

1. Name the file and one function behind the duration report.
2. Explain what disguises it (the 1.1 factor constant fraction longer).
3. Why spelling of a family's name blows up but a barely different spelling sails through (exact string match vs registry).
4. Why the number fetched fails / takes few duration labels as few frequency ones (binning types).
5. Refusing / one caller survives refusal where another is stopped (bank.py tolerates None; get_bank_property and background_bin_from_string raise).
6. Why one bad row stops a whole column (numpy.vectorize doesn't catch).
7. Library theory holds — the 1.1 multiplier, consistent across families/masses, so the underlying LALSimulation theory is intact.
8. Why configuration turns away computable names — argparse choices on named_frequency_cutoffs for --filter-cutoff; background bin types hardcoded; bytes encoding.
9. Why extra-mode figures report longer durations — get_hm_length_in_time scales f_lower by 2/maxm.

Let me write this comprehensively and then call finish with the message.
The analysis is complete. Here is the full answer in prose.

## The file and the one function

**`pycbc/pnutils.py`, function `_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` â lines 527â559**, exported one line later as `get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561). Every symptom in the report routes through this one function; everything else involved either dispatches into it, calls it, or merely resembles it.

## General theory of how it works

The body first coerces only the five **numeric** inputs (`m1, m2, s1z, s2z, f_low = float(...)`); `approximant` is left untouched and compared by **exact string equality** against six literals, each choosing one LALSimulation call:

| branch | LALSimulation call |
|---|---|
| `"SEOBNRv2"` | `SimIMRPhenomBComputeChi` + `SimIMRSEOBNRv2ChirpTimeSingleSpin` |
| `"IMRPhenomXAS"` | `SimIMRPhenomXASDuration` |
| `"IMRPhenomD"` | `SimIMRPhenomDChirpTime` |
| `"SEOBNRv4"` | `SimIMRSEOBNRv4ROMTimeOfFrequency` |
| `"SEOBNRv5_ROM"` | `SimIMRSEOBNRv5ROMTimeOfFrequency` |
| `"SPAtmplt"` / `"TaylorF2"` | `SimInspiralTaylorF2ReducedSpinComputeChi` + `...ChirpTime` |

Anything else hits `raise RuntimeError("I can't calculate a duration for %s" % approximant)` (line 556) â raised **before** any LALSimulation call, so it is a PyCBC literal, not a LAL error. Every surviving branch ends with **`return time_length * 1.1`** (line 559).

## What disguises the constant fraction

The `* 1.1` at line 559. It is a flat 10% safety margin applied to **every** accepted family, mass and spin, so the reported duration is always exactly 1.1 Ã the LALSimulation figure for the same parameters. Because it is a pure multiplicative constant it leaves rankings, bin orderings and ratios unchanged, which is why the underlying library theory still "holds" â nothing in LALSimulation is wrong; the inflation is added afterward in PyCBC and is invisible unless you compare against the raw `SimIMR*` return.

## Why one spelling blows up and a near-identical one sails through

`_get_imr_duration` keys on raw literals, while the waveform engine keys on the much larger `_filter_time_lengths` registry in `pycbc/waveform/waveform.py` (lines 1085â1099, plus `_INTERP` aliases minted by `td_fd_waveform_transform` at 1154â1158). That registry contains `SEOBNRv4_ROM`, `SEOBNRv4P`, `SEOBNRv4HM_ROM`, `IMRPhenomPv2`, `IMRPhenomPv3HM`, `SpinTaylorT5`, `EOBNRv2_ROM`, etc. â none of which are literals here. So `"SEOBNRv4"` is accepted for both purposes while `"SEOBNRv4_ROM"` filters fine but is refused as a duration name; conversely `"SEOBNRv5_ROM"` is accepted while `"SEOBNRv5"` is refused. The bridge functions are one-line adapters (`seobnrv4_length_in_time` â `get_imr_length("SEOBNRv4", ...)` at waveform.py:1028â1041) that quietly re-spell the name; callers that go through `pnutils` directly get no such rescue. A second, silent spelling trap: `pycbc/tmpltbank/bank_output_utils.py:322` stores the approximant column **encoded** (`approximant.encode()`), and `get_bank_property` reads `bank['approximant'][:]` without decoding â in Python 3 `b'SEOBNRv4' == 'SEOBNRv4'` is `False`, so even a perfectly correct name can be refused row by row.

## Why one caller survives the refusal and another is stopped

- **Survives (template generation):** `make_waveform` in `pycbc/waveform/bank.py:599â601` goes through the registry wrapper `get_waveform_filter_length_in_time` (waveform.py:1387â1395), which returns `None` on a miss; the caller then raises a clean `RuntimeError('Template waveform %s not recognized!')`. `pycbc/filter/matchedfilter.py:1809â1812`, `find_variable_start_frequency` (bank.py:821â837) and `get_fd_waveform_from_td` treat the number only as a sizing hint and proceed without it.
- **Stopped:** `get_bank_property` (`pycbc/tmpltbank/bank_conversions.py:111â114`) and `background_bin_from_string` (`pycbc/events/coinc.py:116â124`) call `pnutils.get_imr_duration(...)` directly, with no registry lookup and no exception handling, so `_get_imr_duration`'s `RuntimeError` propagates and kills the run.

## Why one bad row stops a whole column

`get_imr_duration = numpy.vectorize(_get_imr_duration)` (pnutils.py:561). `numpy.vectorize` is a Python-level loop that **does not trap exceptions** from the wrapped function; the first row whose approximant is unrecognized (or whose encoded bytes fail the string match) raises, and since the arrays are evaluated as one vectorized call, the entire column is lost â no partial results, and no indication of which row was at fault.

## Why configuration turns away computable names

Three independent gates. (1) `background_bin_from_string` (coinc.py:47â140) recognizes only hardcoded mass/spin types, `SEOBNRv2Peak`/`SEOBNRv4Peak` (line 107), and the three keys of `_APPROXIMANT_DURATION_MAP` (lines 40â44: `SEOBNRv2duration`, `SEOBNRv4duration`, `SEOBNRv5duration`); anything else is `ValueError('Invalid bin type %s')`, so `SEOBNRv4_ROM`/`IMRPhenomD` durations are not reachable even though perfectly computable. (2) The frequency-label side is bounded by `named_frequency_cutoffs` (pnutils.py:456â497), which `--filter-cutoff` enforces via argparse `choices=` (`pycbc/tmpltbank/option_utils.py:1145`) â hence "a few duration labels but few frequency ones": both lists are closed enumerations, just different ones, so a name legal in one vocabulary is rejected by the other. (3) The bytes-vs-str encoding mismatch described above can reject names that are, textually, correct.

## Why extra-mode waveforms report longer durations

`get_hm_length_in_time` (`pycbc/waveform/waveform.py:1057â1069`), registered for `SEOBNRv4HM_ROM` (via `seobnrv4hm_length_in_time`) and `IMRPhenomHM` (via `imrphenomhm_length_in_time`), parses the mode array, takes `maxm = max(m for _, m in mode_array)` and then sets `kwargs['f_lower'] = flow * 2./maxm`. Feeding a **higher** start frequency into the same duration routine yields a **longer** time-to-merger? â no: it yields a shorter inspiral, so note carefully that the direction depends on the underlying `SimIMR*TimeOfFrequency` response to `f_low`; what is unambiguous is that the HM durations are computed at a rescaled `f_lower = 2 f_low / maxm` (e.g. halved for l=4), which is why multi-mode figures differ systematically from their 22-only counterparts by more than the flat 1.1 factor.

Analysis complete, repository untouched (read-only: grep/sed/awk/git-log only).

ANSWER SUMMARY

File and one function: pycbc/pnutils.py, `_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` (lines 527-559), exported at line 561 as `get_imr_duration = numpy.vectorize(_get_imr_duration)`. Every reported symptom routes through it.

- Constant-fraction inflation: the `return time_length * 1.1` on line 559 adds a flat 10% margin to every accepted family/mass/spin, so reports are always exactly 1.1x the LALSimulation figure; library theory itself is intact.
- Spelling blowups: exact string match against only six literals, whereas the waveform engine uses the far larger `_filter_time_lengths` registry (plus `_INTERP` aliases). So SEOBNRv4_ROM/SEOBNRv4P/SEOBNRv4HM_ROM/SEOBNRv5 are refused while SEOBNRv4/SEOBNRv5_ROM pass. A second trap: bank_output_utils.py:322 stores the approximant encoded (`b'SEOBNRv4'`), and get_bank_property never decodes, so even correct names fail in Python 3.
- One caller survives, one stops: bank.py:599-601 uses the registry wrapper `get_waveform_filter_length_in_time` (returns None on miss, converted to a clean RuntimeError); matchedfilter.py:1809 and find_variable_start_frequency treat it as a hint. But `get_bank_property` (bank_conversions.py:111-114) and `background_bin_from_string` (coinc.py:116-124) call pnutils.get_imr_duration directly with no guard, so the RuntimeError propagates.
- One bad row kills the column: numpy.vectorize is a plain Python loop that does not trap exceptions, so the first refused row aborts the whole vectorized call with no partial output.
- Config turning away computable names: closed enumerations on both sides — `_APPROXIMANT_DURATION_MAP` (only v2/v4/v5 duration keys) and `named_frequency_cutoffs` enforced by argparse `choices=` (option_utils.py:1145); plus the bytes/str mismatch.
- Extra modes: `get_hm_length_in_time` (waveform.py:1057-1069) rescales `f_lower = flow * 2/maxm` from the mode array, so HM durations differ systematically from 22-mode ones beyond the flat 1.1 factor.