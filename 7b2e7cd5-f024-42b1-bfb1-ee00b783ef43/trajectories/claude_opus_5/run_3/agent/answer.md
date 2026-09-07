I've finished reading the relevant code. No files were created, modified, or deleted; everything below is from read-only inspection of `/workspace/gwastro__pycbc__f1e16ea5`.

## The one function behind the constant-fraction inflation

`pycbc/pnutils.py`, `_get_imr_duration` (defined at line 527). Every branch of the function calls straight into LALSimulation for the honest number — `SimIMRSEOBNRv2ChirpTimeSingleSpin`, `SimIMRPhenomXASDuration`, `SimIMRPhenomDChirpTime`, `SimIMRSEOBNRv4ROMTimeOfFrequency`, `SimIMRSEOBNRv5ROMTimeOfFrequency`, or `SimInspiralTaylorF2ReducedSpinChirpTime` — and then, *after* the whole if/elif chain, at line 559 it does:

```
return time_length * 1.1
```

That single unconditional multiplication is the "constant fraction". It is applied outside the branch structure, so it is family-independent and mass-independent: every duration this function ever returns is exactly 10 % above what the wave library reported for the same masses, spins and `f_lower`. There is no keyword to turn it off, and the function's docstring in this checkout is empty, so nothing announces it.

**Why it disguises itself.** The theory the library holds is sound for the function's *original* consumer: durations here are used to size filter buffers. `FilterBank.get_template` (`pycbc/waveform/bank.py:599-604`) does `tlen = round_up((buff_size + min_buffer) * sample_rate)`, and `followup_event_significance` (`pycbc/filter/matchedfilter.py:1811`, 1835, 1867) uses it to choose a lookback window. For those uses an estimate *must* be an over-estimate — a 10 % pad is a safety margin and is invisible, because nothing downstream compares it to a reference. The same number, however, escapes into places where it is treated as a physical observable: the `template_duration`/`duration` column built by `pycbc/tmpltbank/bank_conversions.py:110-122`, the `SEOBNRv*duration` background bins in `pycbc/events/coinc.py:117-125`, `get_param('template_duration')` in `pycbc/events/triggers.py:130-137`, `pycbc_page_sensitivity` line 153, and `pycbc_plot_bank_corner`. There the pad is a systematic bias, and it is precisely there that someone comparing against `lalsimulation` notices the constant ratio.

There is a second, related inconsistency worth knowing: for `TaylorF2`/`SPAtmplt` two different duration paths exist. `_filter_time_lengths["TaylorF2"] = spa_length_in_time` (`pycbc/waveform/waveform.py:1085-1086`) goes to `findchirp_chirptime` with *no* 1.1 factor, whereas `_get_imr_duration`'s `'SPAtmplt' or 'TaylorF2'` branch goes to the reduced-spin LAL routine *and* multiplies by 1.1. So a bank whose `template_duration` column was written by `pycbc/tmpltbank/bank_output_utils.py:329` (which uses `get_waveform_filter_length_in_time`, i.e. the un-padded path) will disagree by ~10 % plus a model difference with the same quantity recomputed by `bank_conversions.get_bank_property`.

## Why one caller survives the refusal and the other does not

The `else` at the end of the chain (`pycbc/pnutils.py:555-556`) raises `RuntimeError("I can't calculate a duration for %s")` for any approximant string not literally equal to one of the six names it knows. Whether a caller survives that depends on whether it reaches `_get_imr_duration` through the adapter layer or directly.

The adapter is `_filter_time_lengths` in `pycbc/waveform/waveform.py:1085-1116` plus the thin wrappers `seobnrv2/seobnrv4/seobnrv5/imrphenomd_length_in_time` (lines 1023-1041). That table is a **name translator**: twenty-eight pycbc-level approximant names map onto only five LAL-level names, so `SEOBNRv4_ROM`, `SEOBNRv4P`, `SEOBNRv2_ROM_DoubleSpin_HI`, `IMRPhenomPv2_NRTidal`, `IMRPhenomXPHM` etc. are all rewritten to `"SEOBNRv4"`, `"IMRPhenomD"`, … before `pnutils` ever sees them. And the front door, `get_waveform_filter_length_in_time` (line 1387), is a *membership test*, not a call:

```
if approximant in _filter_time_lengths:
    return _filter_time_lengths[approximant](**kwargs)
else:
    return None
```

So an unknown name here degrades to `None`, silently. Callers of the direct route have no such shield: `bank_conversions.get_bank_property`, `coinc.background_bin_from_string`, `triggers.get_param` and the two plotting scripts hand the raw approximant string (often the `approximant` column read out of the bank file) into `pnutils.get_imr_duration`, where an unrecognised spelling is a hard `RuntimeError`. Note also that `get_inspiral_tf` (`pycbc/pnutils.py:576-580`) *does* normalise variants by truncating to the `SEOBNRv*` prefix; `_get_imr_duration` has no equivalent normalisation, which is exactly why "barely different spellings" (`SEOBNRv5` vs `SEOBNRv5_ROM`, anything with an `_ROM`/`HM`/`P` suffix) sail or fail seemingly at random. A further spelling trap: HDF5 string columns come back as `numpy.bytes_`, and `b'SEOBNRv4' == "SEOBNRv4"` is `False` in Python 3, so a bank read via raw `h5py` fails every comparison and falls through to the raise. `FilterBank.approximant` (`pycbc/waveform/bank.py:452-455`) decodes explicitly; `bank_conversions.py:105` does not.

Downstream of the `None`, survival differs again. `FilterBank.get_template` converts it into a clear error (`if not buff_size: raise RuntimeError('Template waveform %s not recognized!')`, lines 600-601). The decompression path at `bank.py:721-727` survives even an unknown approximant, because it only calls the estimator when the stored `template_duration` is absent or zero. `followup_event_significance` would not survive: it does arithmetic on the returned value directly, so a `None` becomes a `TypeError` far from the cause.

## Why one bad row stops the whole column

`pycbc/pnutils.py:561`: `get_imr_duration = numpy.vectorize(_get_imr_duration)`. `numpy.vectorize` is a Python-level loop with broadcasting, including over keyword arguments — so in `bank_conversions.get_bank_property` (lines 103-122) the whole `approximant` column is broadcast against the mass/spin columns and `_get_imr_duration` is invoked once per template. There is no per-element error handling anywhere on that path. The first template whose approximant string is not one of the six literals raises, the exception propagates out of the vectorised loop, and the entire `template_duration`/`duration`/`premerger_duration` column for the bank is lost — even though every other row was perfectly computable. This is the "one bad row kills a column" behaviour: mixed-approximant banks are a normal product of `--approximant` conditionals (`bank.py:104-126`, `parse_approximant_arg`), so a single exotic family in an otherwise ordinary bank takes out the plot, the cut, or the binning.

Two related `vectorize` fragilities on the same line: it caches the output dtype from the first successful call, and it refuses size-0 input entirely (`ValueError: cannot call 'vectorize' on size 0 inputs unless 'otypes' is set`), so an empty `template_ids` — which is exactly what an earlier aggressive cut produces in `apply_template_cuts` — errors instead of returning an empty array.

## Why the configuration layer turns away names that are perfectly computable

Two independent problems, both in `pycbc/events/cuts.py`.

First, the whitelist is narrower than the capability. `convert_inputstr` (line 104) rejects anything not in `template_param_choices = bank_conv.conversion_options + template_fit_param_choices`, and `conversion_options` (`bank_conversions.py:35-39`) is a hand-maintained list of eighteen names. But `get_bank_property` itself is far more permissive: its first branch is `if parameter in bank`, i.e. *any* column present in the file, and its second branch is `elif parameter.endswith('duration')`, i.e. any duration-suffixed name. So a cut on a column that demonstrably exists in the bank (`f_final`, `f_lower`, `tau0`, a pipeline-specific column) is refused at parse time with `NotImplementedError` although the conversion function would have returned it immediately. The whitelist and the implementation have drifted apart, and only the whitelist is consulted.

Second, case handling is inconsistent within the same six lines. `convert_inputstr` validates with `cut_param.lower() not in choices` and `cut_limit.lower() not in ineq_choices`, but then builds the returned key with the *original* strings: `return {(cut_param, ineq_functions[cut_limit]): cut_value}` (line 120). Consequences: `MCHIRP:5:upper` passes validation and is stored under `'MCHIRP'`, and then `apply_template_cuts` (line 437) re-tests `parameter in bank_conv.conversion_options` — case-sensitively this time — misses, misses `template_fit_param_choices` too, and lands in the branch that raises `ValueError("Cut parameter … not recognised. This shouldn't happen with input sanitisation")`. That error message is literally the code telling you the two checks disagree. Symmetrically, `mchirp:5:Upper` passes the `.lower()` inequality check and then dies with `KeyError: 'Upper'` on `ineq_functions[cut_limit]` in the same expression.

A third, milder refusal lives in `pycbc/events/coinc.py:38-43`: `_APPROXIMANT_DURATION_MAP` recognises exactly three duration bin names (`SEOBNRv2duration`, `SEOBNRv4duration`, `SEOBNRv5duration`) against a similarly tiny frequency set (`SEOBNRv2Peak`, `SEOBNRv4Peak` at line 107); anything else is `ValueError('Invalid bin type')`. And in `pycbc/events/triggers.py:142-147` the fall-through is worse than a refusal: an unrecognised parameter name is silently *reinterpreted as a frequency-function name* and passed to `pnutils.get_freq`, which does `getattr(lalsim, freqfunc)`. A mistyped duration label therefore surfaces as an `AttributeError` about a LAL symbol that the user never mentioned — the "duration label taken for a frequency one" behaviour.

## Why extra-mode waveforms report longer durations

`get_hm_length_in_time` in `pycbc/waveform/waveform.py:1057-1068`, reached via `imrphenomhm_length_in_time` (line 1043, registered for `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXHM`, `IMRPhenomXPHM`) and `seobnrv4hm_length_in_time` (line 1050, registered for `SEOBNRv4HM_ROM`).

The mechanism is a frequency rescale, not a duration rescale. There is no LAL duration routine for higher-mode models, so these wrappers estimate the multi-mode length using the *dominant-mode* model (`IMRPhenomD` or `SEOBNRv4`) but started at a lower frequency:

```
kwargs = parse_mode_array(kwargs)
maxm = max(m for _, m in kwargs['mode_array'])   # else maxm_default
kwargs['f_lower'] = flow * 2./maxm
return get_imr_length(lor_approx, **kwargs)
```

The physics is that the (ℓ,m) mode radiates at roughly m/2 times the orbital-quadrupole frequency, so the m-th mode enters the band when the (2,2) mode is at `2·f_lower/m`; to cover all modes you must start the (2,2) clock at `f_lower·2/m_max`. Because chirp time grows steeply as `f_lower` falls (∼f⁻⁸ᐟ³ at leading order), even a modest rescale is a large duration increase. The defaults are `maxm_default = 4` for the Phenom-HM family (so `f_lower/2`) and `5` for `SEOBNRv4HM_ROM` (so `0.4·f_lower`), and an explicit `mode_array` overrides them via `parse_mode_array` (line 395). This is deliberate and correct as a *buffer* estimate, but it is not the physical duration of the multi-mode waveform, and — being routed through `get_imr_length` → `_get_imr_duration` — it also carries the ×1.1 pad on top. So a higher-mode template's reported duration is longer for two stacked reasons, one intentional and one hidden.

One fragility in that branch: `max(m for _, m in mode_array)` does not take an absolute value. A `mode_array` written with negative-m entries only (e.g. `[[2,-2]]`, a legal spelling that `parse_mode_array` accepts) yields `maxm = -2` and therefore a **negative** `f_lower` handed to LAL. Mixed arrays like `[[2,2],[2,-2]]` are unaffected because the positive entry wins.

## Summary of where each behaviour lives

- Constant ~10 % inflation, all families, all masses: `pycbc/pnutils.py:559`, `return time_length * 1.1`, applied after every branch of `_get_imr_duration`.
- Spelling sensitivity: exact string equality in `_get_imr_duration`'s if/elif chain with no prefix normalisation (contrast `get_inspiral_tf`, `pnutils.py:576`) and no bytes decoding at `bank_conversions.py:105`; the `else` at line 555 raises.
- One caller survives, the other doesn't: `_filter_time_lengths` (`waveform.py:1085-1116`) translates names before they reach `pnutils`, and `get_waveform_filter_length_in_time` (line 1387) returns `None` instead of raising; direct `pnutils.get_imr_duration` callers get the `RuntimeError`.
- One bad row kills a column: `numpy.vectorize` at `pnutils.py:561` with no per-element guard, driven column-wise from `bank_conversions.py:110-122`.
- Computable names refused by configuration: the hand-maintained `conversion_options` whitelist (`bank_conversions.py:35-39`) is narrower than `get_bank_property`'s `in bank` / `endswith('duration')` branches, plus the `.lower()`-validate/original-case-store mismatch at `cuts.py:104-120` versus the case-sensitive re-check at `cuts.py:437`.
- Extra modes → longer durations: `f_lower * 2./maxm` in `get_hm_length_in_time` (`waveform.py:1057-1068`), with `maxm` defaulting to 4 or 5, then compounded by the 1.1 factor.

I have not changed anything; if you want a fix, the minimal, least-invasive change would be to make the safety factor an explicit, defaulted keyword of `_get_imr_duration` so buffer-sizing callers keep the pad while physical-observable callers can ask for the raw LAL value — but I have deliberately not applied it.

I've gathered enough now. I want to verify a couple details before writing the final answer: the duration map used in coinc.py for bin type names, and confirming that bank_conversions passes the approximant array without decoding it—h5py string datasets typically come back as bytes rather than decoded strings unless stored as variable-length strings.

Since np.vectorize applies element-wise, each approximant element becomes numpy.bytes_, so comparisons like `== "SEOBNRv4"` fail and vectorize raises on the first bad element, aborting computation for the entire column—that's the core issue with get_bank_property. There's also a secondary bug worth noting: using np.zeros_like on template_ids gives an integer dtype for prem_dur, which causes problems when subtracting durations. Time to write up the final answer.

Everything below is analysis only — I made no edits, and the working tree is untouched.

## The one function behind the inflated durations

`_get_imr_duration` in `pycbc/pnutils.py` (definition at line 527). Its if/elif chain dispatches to LALSimulation for each family — `SimIMRSEOBNRv2ChirpTimeSingleSpin`, `SimIMRPhenomXASDuration`, `SimIMRPhenomDChirpTime`, `SimIMRSEOBNRv4ROMTimeOfFrequency`, `SimIMRSEOBNRv5ROMTimeOfFrequency`, and `SimInspiralTaylorF2ReducedSpinChirpTime` for `SPAtmplt`/`TaylorF2` — and then, *outside* the branch structure, at line 559 does:

```
    return time_length * 1.1
```

That single unconditional multiplication is the "constant fraction". Because it sits after the dispatch rather than inside any branch, it is family-independent, mass-independent and spin-independent: every value handed back is exactly 10 % above what the underlying wave library reported for the same masses, spins and starting frequency. The public entry point is `get_imr_duration = numpy.vectorize(_get_imr_duration)` at line 561.

## What disguises it

Three things hide it from a reader who searches for the discrepancy:

1. **Name laundering.** Nobody calls `pnutils` with the approximant they actually asked for. `pycbc/waveform/waveform.py` defines thin wrappers — `seobnrv2_length_in_time`, `seobnrv4_length_in_time`, `seobnrv5_length_in_time`, `imrphenomd_length_in_time` (lines 1024–1041) — each of which calls `get_imr_length(<hard-coded name>, **kwds)` (line 1012). The `_filter_time_lengths` table (lines 1085 onward) then maps roughly thirty PyCBC approximant names onto those handful of wrappers, so `SEOBNRv4_ROM`, `SEOBNRv4P`, `SEOBNRv2_ROM_DoubleSpin_HI`, `IMRPhenomPv2_NRTidal`, `IMRPhenomXPHM` and friends all collapse to `"SEOBNRv4"`, `"IMRPhenomD"` etc. by the time `pnutils` sees them. Grepping for your approximant's name never reaches line 559.
2. **The docstrings are empty** in this checkout (`ast.get_docstring` returns an empty string for `_get_imr_duration`, `get_imr_length`, `get_waveform_filter_length_in_time`), so nothing announces the pad.
3. **The factor is genuinely intentional for the original consumer.** These numbers were built to *size buffers*, not to report physics: `FilterBank.get_template` (`pycbc/waveform/bank.py:599–604`) does `tlen = round_up((buff_size + min_buffer) * sample_rate)`, and `followup_event_significance` (`pycbc/filter/matchedfilter.py:1811, 1835, 1867`) uses it to choose a lookback window. A 10 % over-estimate is harmless there. It only becomes a visible bug once the same function is reused for *reported* durations — `tmpltbank/bank_conversions.get_bank_property`, `events/coinc.background_bin_from_string`, `events/triggers.get_param`, `bin/plotting/pycbc_page_sensitivity`, `bin/plotting/pycbc_plot_bank_corner`. That dual use is the real defect: a buffer safety margin leaking into an observable.

## Why one caller survives a refusal where the others do not

There are two different failure regimes, and which one you land in depends on whether you go through the dictionary or straight to `pnutils`.

* `get_waveform_filter_length_in_time` (`waveform.py:1387–1395`) is a *membership test*: `if approximant in _filter_time_lengths: ... else: return None`. An unrecognised name degrades silently to `None`.
* `_get_imr_duration`'s chain ends in `else: raise RuntimeError("I can't calculate a duration for %s" % approximant)` (line 556). Callers that hand the raw table string to `pnutils.get_imr_duration` get a hard exception for any spelling not in the six-branch list.

So the survivor is `bank.py:721–727` in the decompression path: it only calls the estimator when `template_duration` is missing or zero, gets `None` back for an unknown name, assigns it to `hdecomp.chirp_length`/`length_in_time`, and carries on — the failure surfaces much later as a `TypeError`/nonsense length rather than at the point of refusal. `FilterBank.get_template` at line 599–601 makes the opposite choice: `if not buff_size: raise RuntimeError('Template waveform %s not recognized!')`, converting the same `None` into an immediate error. And `bank_conversions`/`coinc`/`triggers` never touch the dictionary at all, so for them an odd spelling is an outright `RuntimeError` from `pnutils`.

Note also that `pnutils.get_inspiral_tf` (lines ~576–580) *does* normalise family variants, truncating with `approximant[:len('SEOBNRv*')]` before looking up its `tof_func_map`. `_get_imr_duration` has no equivalent normalisation, which is exactly why `SEOBNRv5` versus `SEOBNRv5_ROM`, or any `_ROM`/`HM`/`P` suffix, is the difference between a computed number and an exception.

## Why one bad row stops a whole column

`get_imr_duration` is `numpy.vectorize(_get_imr_duration)`, and `bank_conversions.get_bank_property` (lines 103–122) calls it on whole arrays: `imr_args + ['f_lower']` (or `['f_final']` for the premerger term), with `kwargs = {'approximant': bank['approximant'][:][template_ids]}` when the column exists. `numpy.vectorize` is a Python-level loop with no per-element error handling, so the first element whose approximant string falls through to the `else` raises and aborts the entire array evaluation — one unrecognised template kills the duration for every template in the bank, and `get_bank_property` has no try/except around it. Two aggravating details in the same block:

* **No byte decoding.** `FilterBank.approximant` (`bank.py:452–455`) explicitly does `if hasattr(apx, 'decode'): apx = apx.decode()`. `bank_conversions.py:105` does not. HDF5 string datasets come back as `numpy.bytes_`, and `numpy.bytes_(b'SEOBNRv4') == "SEOBNRv4"` is `False`, so every comparison in the chain fails and the `else` fires for *every* row — a whole-column failure with no bad row at all.
* **Empty input.** `numpy.vectorize` refuses zero-length input unless `otypes` is set (`ValueError: cannot call 'vectorize' on size 0 inputs unless 'otypes' is set`). An empty `template_ids` — entirely reachable from `apply_template_cuts` after an earlier cut removes everything — errors instead of returning an empty array. Relatedly, `prem_dur = np.zeros_like(template_ids)` at line 125 inherits the integer dtype of the id array, so the `values -= prem_dur` at line 131 is an integer-typed subtrahend.

## Why the configuration turns away computable names

The whitelist and the computation disagree about what a name is.

`pycbc/events/cuts.py:53` builds `template_param_choices = bank_conv.conversion_options + template_fit_param_choices`, and `convert_inputstr` (line 104) raises `NotImplementedError` for anything outside it. But `conversion_options` (`bank_conversions.py:35–39`) is a hand-maintained literal list, while `get_bank_property` is far more permissive: its first branch is `if parameter in bank` (any column present in the file), and its second is `elif parameter.endswith('duration')` (any name with that suffix). So a quantity that `get_bank_property` would happily compute is rejected up front purely because someone forgot to add the string to the list. The mismatch is exercised twice more: `apply_template_cuts` (line 437) re-tests `parameter in bank_conv.conversion_options` before dispatching, so even a value that slipped past the parser is dropped, and `bin/plotting/pycbc_plot_bank_corner:179` performs the same membership check with its own `KeyError`.

The spelling asymmetry you noticed lives here too. `convert_inputstr` validates case-insensitively (`cut_param.lower() not in choices`, `cut_limit.lower() not in ineq_choices`) but stores the *original* casing as the dictionary key: `return {(cut_param, ineq_functions[cut_limit]): cut_value}`. So `MCHIRP:5:upper` passes the parser and is then silently discarded by the case-sensitive re-check in `apply_template_cuts`. Separately, in `events/triggers.get_param` the final fallback is `pnutils.get_freq(par, ...)`, and `get_freq` does `getattr(lalsim, freqfunc)` — a mistyped duration label there dies as an `AttributeError` about a missing LAL symbol rather than an unknown parameter, which is why the same class of typo produces such different-looking messages depending on where it enters.

## Why extra-mode waveforms report longer durations

`get_hm_length_in_time` (`waveform.py:1057–1068`), reached via `imrphenomhm_length_in_time` (line 1043, registered for `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXHM`, `IMRPhenomXPHM`) and `seobnrv4hm_length_in_time` (line 1050, for `SEOBNRv4HM_ROM`). The mechanism is a *frequency rescale*, not a longer waveform model — it asks the quadrupole-only routine (`IMRPhenomD` or `SEOBNRv4`) for a duration at an artificially lowered frequency:

```
maxm = max(m for _, m in kwargs['mode_array'])   # else maxm_default
kwargs['f_lower'] = flow * 2./maxm
return get_imr_length(lor_approx, **kwargs)
```

The theory is sound. An (ℓ,m) mode radiates at roughly m/2 times the orbital/quadrupole frequency, so the m-th mode enters the analysis band when the (2,2) mode is still at `2·f_lower/m`; to cover the highest requested mode you must start the (2,2) clock there. Chirp time grows steeply as `f_lower` falls (≈ f^(−8/3) at leading order), so a modest rescale produces a large duration increase. The branches are: an explicit `mode_array` (normalised by `parse_mode_array`, line 395, which accepts strings, lists and numbers) sets `maxm` from the actual modes; otherwise the defaults are `maxm_default = 4` for the Phenom-HM family (giving `f_lower/2`) and `5` for `SEOBNRv4HM_ROM` (giving `0.4·f_lower`).

So a higher-mode template's reported duration is inflated twice over: once by the deliberate `2/maxm` rescale — which is a correct *buffer* estimate but not the physical duration of the multi-mode waveform — and again by the ×1.1 at `pnutils.py:559`, since `get_hm_length_in_time` routes through `get_imr_length` → `_get_imr_duration` like everything else.

## What would need to change (not applied)

The minimal, behaviour-preserving fix is to stop conflating "duration" with "buffer size": make the 1.1 pad an explicit, defaulted parameter of `_get_imr_duration` (or move it up into the buffer-sizing callers in `waveform/bank.py` and `filter/matchedfilter.py`) so that the reporting callers — `bank_conversions.get_bank_property`, `coinc.background_bin_from_string`, `triggers.get_param`, and the two plotting scripts — receive the raw library value. Alongside that: decode byte strings in `bank_conversions.py:105` the way `bank.py:452–455` already does; give `numpy.vectorize` an `otypes=[float]` so empty template lists work; normalise approximant names in `_get_imr_duration` the way `get_inspiral_tf` already does, or catch the `RuntimeError` per element so one bad row cannot void a column; make `prem_dur` float-typed; and reconcile `conversion_options` with the far broader set `get_bank_property` can actually compute, including case-normalising the key stored by `convert_inputstr`. I have deliberately left all of this undescribed in the source itself.