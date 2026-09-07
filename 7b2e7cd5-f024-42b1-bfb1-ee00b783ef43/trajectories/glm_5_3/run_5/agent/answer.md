I was in the middle of writing my final answer. Let me complete it now.
I have all the evidence I need. Here is my complete analysis.

## Answer

**File:** `pycbc/pnutils.py` â **Function:** `_get_imr_duration` (lines 527-559), exported as `get_imr_duration = numpy.vectorize(_get_imr_duration)` on line 561.

Every symptom in the report traces to this one function and to how its callers reach it.

### The mechanism

`_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` is a plain `if`/`elif` string-equality ladder over the approximant name:

- `"SEOBNRv2"` â `SimIMRSEOBNRv2ChirpTimeSingleSpin` (with `chi = SimIMRPhenomBComputeChi`)
- `'IMRPhenomXAS'` â `SimIMRPhenomXASDuration`
- `"IMRPhenomD"` â `SimIMRPhenomDChirpTime`
- `"SEOBNRv4"` â `SimIMRSEOBNRv4ROMTimeOfFrequency`
- `'SEOBNRv5_ROM'` â `SimIMRSEOBNRv5ROMTimeOfFrequency`
- `'SPAtmplt'` / `'TaylorF2'` â `SimInspiralTaylorF2ReducedSpinChirpTime` with `-1` as the phase order
- **anything else** â `raise RuntimeError("I can't calculate a duration for %s" % approximant)`

Seven spellings accepted; everything else refused.

### The constant fraction (the `* 1.1`)

Line 559 is `return time_length * 1.1`. The multiplier is applied *after* the ladder, identically for every family and every mass range, and it is a scalar constant. So the reported duration is always exactly 10% larger than the underlying waveform library's own answer for the same masses, spins and starting frequency. There is no mass-dependent or family-dependent correction anywhere: whatever LALSimulation returns is inflated by a fixed factor and nothing else touches it. That is precisely why the discrepancy is "a constant fraction longer than the figure the underlying waveform library gives... across every family and mass range." The factor exists as a safety margin (filters need extra room), and note it is applied *only* on this path â the sibling functions in the same file never add it.

### Spelling sensitivity

Because the dispatch is exact string equality against seven literals, any variant spelling (`SEOBNRv4HM_ROM`, `SEOBNRv5`, `IMRPhenomXPHM`, a trailing `_INTERP` suffix, different capitalisation) misses every branch and falls into the final `RuntimeError`. This is not LALSimulation refusing the name â the exception is raised by PyCBC *before* any library call, and the message names the string it failed to match. So "the failure is the wave library refusing an unknown name" is the appearance; in reality the library was never asked.

### Why duration lookups fail where frequency lookups don't

The neighbouring name-dispatch code is more forgiving, which is why the two behave differently:

- `get_freq` / `_get_freq` and `frequency_cutoff_from_name` (pnutils.py ~line 357-525) go through `getattr(lalsim, freqfunc)` and a *named* dictionary `{'SchwarzISCO', 'IMRPhenomBFinal', ..., 'SEOBNRv5RD', 'SEOBNRv5Peak'}`, and `get_final_freq` special-cases `'IMRPhenomD'`, `'IMRPhenomXAS'`, `'SEOBNRv5'` before falling back to `lalsim.GetApproximantFromString(approx)` â so a name that is a genuine LALSimulation approximant still resolves.
- `_get_imr_duration` has no `GetApproximantFromString` fallback and no generic path. It only knows its seven strings. This is the asymmetry that makes "few duration labels" fail where "few frequency ones" succeed: a name can be perfectly valid to LALSimulation and still be rejected here.

### Why one caller survives the refusal

There are two consumption routes, and they fail in opposite ways:

1. **Direct call â hard failure.** `pycbc/events/triggers.py:134`, `pycbc/events/coinc.py:117` (via `_APPROXIMANT_DURATION_MAP = {'SEOBNRv2duration': 'SEOBNRv2', 'SEOBNRv4duration': 'SEOBNRv4', 'SEOBNRv5duration': 'SEOBNRv5_ROM'}`), and `pycbc/tmpltbank/bank_conversions.py:111/119` all call `pnutils.get_imr_duration(...)` with **no try/except**. Because `get_imr_duration` is `numpy.vectorize`d, it loops the scalar function over the whole array of templates; the first template whose `approximant` string is not one of the seven raises, and the exception propagates out of the vectorized call and aborts the operation. **One bad row stops the whole column** â nothing is returned, not even the rows that would have worked.

2. **Registry call â silent skip.** `get_waveform_filter_length_in_time` (waveform.py:1387-1395) looks the name up in the `_filter_time_lengths` dict:
   ```python
   if approximant in _filter_time_lengths:
       return _filter_time_lengths[approximant](**kwargs)
   else:
       return None
   ```
   An unregistered name does **not** raise â it returns `None`. Callers such as `pycbc/waveform/bank.py:599-601` then check `if not buff_size: raise RuntimeError('Template waveform %s not recognized!' % approximant)`, while others (`bank.py:722-728`, which falls back to `template_duration` stored in the bank) proceed with `None` or use a stored value. So the same unknown spelling that crashes route 1 is either a *different, clearer* error or a silent `None` in route 2. That is why "one caller survives refusal."

### Why configuration turns away computable names

The configuration surfaces only expose fixed strings. `background_bin_from_string` only offers `SEOBNRv2duration`, `SEOBNRv4duration`, `SEOBNRv5duration` (coinc.py:40-44) â three families out of the seven the function can compute. `bank_conversions.get_bank_property` likewise only reaches `get_imr_duration` when the bank lacks a stored `template_duration` column. So names that `_get_imr_duration` could compute perfectly well cannot be selected through these entry points, while names that *can* be selected are exactly the three hardcoded ones.

### Why extra-mode waveforms report longer durations

`get_hm_length_in_time` (waveform.py:1057-1068) is the reason. For `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXHM`, `IMRPhenomXPHM` it calls `imrphenomhm_length_in_time` (which delegates with `maxm_default = 4`), and for `SEOBNRv4HM_ROM` it uses `seobnrv4hm_length_in_time` (with `maxm_default = 5`). The body does:

```python
kwargs = parse_mode_array(kwargs)
if 'mode_array' in kwargs and kwargs['mode_array'] is not None:
    maxm = max(m for _, m in kwargs['mode_array'])
else:
    maxm = maxm_default
...
kwargs['f_lower'] = flow * 2./maxm
return get_imr_length(lor_approx, **kwargs)
```

It **lowers the effective starting frequency** by the factor `2/maxm` before asking for the duration. A lower `f_lower` means a longer inspiral, so the returned duration is larger than the 22-mode answer at the nominal `f_lower`. Higher modes thus look "longer" not because of any physics of the modes themselves but because the estimator deliberately starts the clock earlier so the waveform generator has room for the harmonics. This is the "symbols mechanism" â the `mode_array` symbols determine `maxm`, which determines the scaling.

### Summary

`_get_imr_duration` in `pycbc/pnutils.py` is the single choke point. Its exact-string dispatch refuses anything outside seven literals; its final `return time_length * 1.1` imposes a fixed +10% on every family and mass range; its lack of an `lalsim.GetApproximantFromString` fallback makes it stricter than the frequency functions beside it; its direct callers crash on the first unknown string because `numpy.vectorize` propagates the scalar `RuntimeError` out of the whole array, while the `_filter_time_lengths` registry route returns `None` instead; the configuration layer only exposes three of the seven accepted spellings; and the HM wrappers inflate durations by rescaling `f_lower` by `2/maxm`.

No files were created, modified or deleted during this analysis.

Task complete. Analysis delivered in prose.

**File/function identified:** `pycbc/pnutils.py`, `_get_imr_duration` (lines 527-559), exported as `get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561).

**Findings:**
1. **Constant fraction longer** - line 559 `return time_length * 1.1` applies a fixed +10% scalar to every family and mass range, after the dispatch ladder. No mass- or family-dependent correction exists.
2. **Spelling sensitivity** - exact string-equality against only seven literals (`SEOBNRv2`, `IMRPhenomXAS`, `IMRPhenomD`, `SEOBNRv4`, `SEOBNRv5_ROM`, `SPAtmplt`, `TaylorF2`); any variant falls to `raise RuntimeError("I can't calculate a duration for %s")` raised by PyCBC itself, not LALSimulation.
3. **Duration vs frequency asymmetry** - sibling `get_freq`/`get_final_freq` have `lalsim.GetApproximantFromString` fallbacks and a named-cutoff dict, so names valid to LALSimulation resolve there but are refused here.
4. **One caller survives, one row kills a column** - direct callers (`events/triggers.py:134`, `events/coinc.py:117`, `tmpltbank/bank_conversions.py:111/119`) have no try/except, and `numpy.vectorize` propagates the first scalar `RuntimeError` out of the whole array, aborting all rows. The registry route `get_waveform_filter_length_in_time` (waveform.py:1387-1395) returns `None` for unknown names instead of raising.
5. **Configuration turns away computable names** - `_APPROXIMANT_DURATION_MAP` (coinc.py:40-44) exposes only 3 of the 7 accepted spellings.
6. **Extra modes report longer durations** - `get_hm_length_in_time` (waveform.py:1057-1068) rescales `kwargs['f_lower'] = flow * 2./maxm` before calling the estimator; the lower start frequency yields a longer duration by construction.

No files were created, edited, or deleted. The working tree is unchanged.