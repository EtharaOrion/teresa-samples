The user wants me to finish. My previous messages have been getting garbled. I need to send one clean, complete final message and then call finish. Let me write it carefully and completely, based on everything I verified:

1. **File and function**: `pycbc/pnutils.py`, `_get_imr_duration` (lines 527–559), exported as `get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561). Refusal at line 556.

2. **Constant fraction longer**: `return time_length * 1.1` — exactly 10% longer for every family.

3. **Spelling fine but unknown name refused**: exact string equality on approximant; only 6 spellings accepted: "SEOBNRv2", "IMRPhenomXAS", "IMRPhenomD", "SEOBNRv4", "SEOBNRv5_ROM", "SPAtmplt"/"TaylorF2". The "SEOBNRv5duration" bin in coinc.py maps to "SEOBNRv5_ROM" precisely because "SEOBNRv5" alone would be refused. Any other name → RuntimeError "I can't calculate a duration for %s".

4. **One caller survives**: `get_waveform_filter_length_in_time` (waveform.py 1387–1395) returns None if approximant not in `_filter_time_lengths`; bank.py falls back (zeros at 503–505, or `get_template` raises a specific error only if falsy).

5. **One bad row stops whole column**: `get_bank_property` passes the whole approximant array; numpy.vectorize has no per-element error handling; the RuntimeError propagates and destroys the entire call. I demonstrated this empirically.

6. **Library theory holds**: every branch calls a LALSimulation ROM time-of-frequency/chirp-time helper with the same masses/spins/f_low; consistent across families.

7. **Configuration turns away computable names**: the exact-string enumeration, not a capability query. Note also that PyCBC's own LALSimulation approximant lists (waveform.py 284–330, `SimInspiralImplementedTDApproximants`/`FDApproximants` + `GetApproximantFromString`) accept far more names — e.g. `get_final_freq` at pnutils 451 uses `lalsim.GetApproximantFromString(approx)` which does generic lookup — while `_get_imr_duration` refuses them.

8. **Extra modes report longer**: `get_hm_length_in_time` (waveform.py 1057–1068): `kwargs['f_lower'] = flow * 2./maxm` with maxm from parse_mode_array (default 4 for IMRPhenomHM-family via `imrphenomhm_length_in_time`, 5 for `SEOBNRv4HM_ROM` via `seobnrv4hm_length_in_time`). Lowering start frequency raises chirp time steeply (~f^-8/3), so HM durations are much longer, plus the 1.1 fudge. Same symbol/function behind it: `_get_imr_duration`'s `* 1.1` on the `get_imr_length` path.

Now let me write this as clean prose. I should be careful to write it in full sentences. I'll keep it structured but flowing prose as requested ("Answer in prose"). I'll use headings for readability.

Let me write the final answer now.
The behavior you described all traces back to a single function in one file.

**The file and the one function**

`pycbc/pnutils.py`, the private function `_get_imr_duration` (lines 527–559). It is the only place in the repository that raises this error (line 556):

```python
raise RuntimeError("I can't calculate a duration for %s" % approximant)
```

and it is published on line 561 as `get_imr_duration = numpy.vectorize(_get_imr_duration)`. Every caller — `get_bank_property` in `pycbc/tmpltbank/bank_conversions.py`, `background_bin_from_string` in `pycbc/events/coinc.py` (via the `_APPROXIMANT_DURATION_MAP` of `'SEOBNRv2duration'`, `'SEOBNRv4duration'`, `'SEOBNRv5duration'`), and `get_imr_length` in `pycbc/waveform/waveform.py` — funnels into this one function.

**The general theory, and the constant-fraction fudge**

The theory the library implements is uniform: every branch of the if/elif chain hands the same four parameters (`m1`, `m2`, `s1z`, `s2z`) and the same `f_low` to a LALSimulation ROM "time of frequency" / chirp-time helper specific to that family — `SimIMRSEOBNRv2ChirpTimeSingleSpin` (preceded by `SimIMRPhenomBComputeChi`), `SimIMRPhenomXASDuration`, `SimIMRPhenomDChirpTime`, `SimIMRSEOBNRv4ROMTimeOfFrequency`, `SimIMRSEOBNRv5ROMTimeOfFrequency`, or `SimInspiralTaylorF2ReducedSpinChirpTime` for the `'SPAtmplt'`/`'TaylorF2'` branch. That is the "library theory holds" part: the underlying figure is always the ROM time-to-merge from `f_low` for the given masses and spins.

The last line of the function is `return time_length * 1.1`. This is applied to every family, every mass, every spin, identically, so a PyCBC-reported duration is always exactly **10% longer** than the figure the underlying library gives for the same masses, spins and starting frequency. That single multiplication is the whole of the constant-fraction behavior, and it is the same symbol that resurfaces as `chirp_length` / `length_in_time` on the filter.

**Spelling is fine; the name is simply not enumerated**

The dispatch is exact string equality against six spellings: `"SEOBNRv2"`, `"IMRPhenomXAS"`, `"IMRPhenomD"`, `"SEOBNRv4"`, `"SEOBNRv5_ROM"`, and `"SPAtmplt"`/`"TaylorF2"`. Nothing checks whether LALSimulation can actually compute the duration. If the name is not one of those literals, control falls to the `else` and the `RuntimeError` fires, even for names that are perfectly computable elsewhere in the same code base — for instance `pycbc/pnutils.py:451` (`get_final_freq`) uses `lalsim.GetApproximantFromString(approx)` and so accepts a much larger set, and `pycbc/waveform/waveform.py` builds its approximant tables from `SimInspiralImplementedTDApproximants`/`...FDApproximants`. The clearest internal evidence that this is an enumeration problem rather than a capability problem is `pycbc/events/coinc.py:43`, which defines `'SEOBNRv5duration': 'SEOBNRv5_ROM'`: the translation table exists precisely so the bin name survives, because passing `'SEOBNRv5'` straight through would be refused, while `SEOBNRv5_ROM` (also used by `seobnrv5_length_in_time` → `get_imr_length("SEOBNRv5_ROM", ...)`) is accepted. So a differently-spelled but otherwise fine name is turned away by configuration — the hard-coded string list — not by the physics.

**Why one caller survives the refusal and another cannot**

The waveform-generation path survives because `get_waveform_filter_length_in_time` (`pycbc/waveform/waveform.py:1387–1395`) first tests `if approximant in _filter_time_lengths` and otherwise returns `None` instead of raising. Downstream, `pycbc/waveform/bank.py:503–505` fills a zero `template_duration` column when it is missing, and `get_template` only complains later if the resulting buffer size is falsy. So an unknown-to-duration name still generates waveforms.

The duration-column path has no such guard. `get_bank_property` builds `kwargs = {'approximant': bank['approximant'][:][template_ids]}` whenever the bank carries an `approximant` column and calls `pnutils.get_imr_duration(...)`. If the bank has no `approximant` column, `kwargs` is empty and every row silently falls back to the default `approximant="SEOBNRv4"` — which is its own (silent) hazard.

**Why one bad row stops a whole column**

`get_imr_duration` is `numpy.vectorize(_get_imr_duration)`, and `numpy.vectorize` has no per-element error handling: it loops, and an exception raised on any single row propagates out of the entire call. I confirmed this empirically — vectorizing the same function over `[SEOBNRv4, SEOBNRv4, SEOBNRv5]` raises `RuntimeError` and returns no array at all, so the two good rows are lost along with the bad one. Because the whole `approximant` array is passed as one keyword argument, a single unrecognized spelling anywhere in the bank aborts the entire duration computation for every template.

**Why extra-mode waveforms report longer durations**

For higher-mode approximants the length entry points are `imrphenomhm_length_in_time` (IMRPhenomHM-family, default `maxm = 4`) and `seobnrv4hm_length_in_time` (`SEOBNRv4HM_ROM`, default `maxm = 5`), both of which call `get_hm_length_in_time` (`pycbc/waveform/waveform.py:1057–1068`):

```python
kwargs = parse_mode_array(kwargs)
...
maxm = max(m for _, m in kwargs['mode_array'])
kwargs['f_lower'] = flow * 2./maxm
return get_imr_length(lor_approx, **kwargs)
```

`parse_mode_array` supplies `maxm` from an explicit `mode_array` if one is given, otherwise the default. Scaling the starting frequency down by `2/maxm` (one-half for `maxm = 4`, two-fifths for `maxm = 5`) pushes the chirp-time integral to a much lower frequency, and since the dominant scaling goes roughly as `f^(-8/3)`, the reported duration grows substantially; the `* 1.1` fudge from `_get_imr_duration` is applied on top since `get_imr_length` calls straight back into it. The mechanism, not any separate HM model, is what makes extra-mode durations longer: the same `_get_imr_duration` is simply handed a lower `f_lower`.

**Summary of the disguise**

The refusal looks like a physics limitation but is a string-enumeration mismatch inside `_get_imr_duration`; the uniform 10% inflation is one literal `* 1.1`; the column-wide failure is `numpy.vectorize` lacking per-row error isolation combined with `get_bank_property` passing the approximant array wholesale; and the longer HM durations are `f_lower * 2./maxm` in `get_hm_length_in_time`, feeding the very same duration function. A fix, if one were wanted, would mean widening or replacing the hard-coded string list with the LALSimulation capability lookup, isolating per-row failures in the vectorized call, and documenting the 1.1 fudge — but per your instruction I have made no changes.

Task complete. The analysis identified `pycbc/pnutils.py::_get_imr_duration` (lines 527-559, exported as the vectorized `get_imr_duration` on line 561) as the single function behind every reported symptom: the constant 10% inflation (`return time_length * 1.1`), the refusal of otherwise-valid approximant names (exact-string if/elif enumeration ending in `raise RuntimeError("I can't calculate a duration for %s")`), the whole-column failure (`numpy.vectorize` plus `get_bank_property` passing the entire approximant array), the surviving caller (`get_waveform_filter_length_in_time` returning None and `bank.py`'s fallback), and the longer extra-mode durations (`get_hm_length_in_time`'s `f_lower * 2./maxm` feeding the same function). No files were created, edited or deleted.