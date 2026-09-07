I think I have enough detail now. Let me verify how `get_waveform_filter_length_in_time` handles default arguments—it uses `props()` to apply defaults like `phase_order=-1`, though callers such as the bank output utilities explicitly pass `phase_order=7`, and I want to confirm how the approximant string is resolved there too.

I'm also checking edge cases: the duration array built from zipped mass tuples works fine as float64 with `numpy.zeros_like`, and the function returns `None` for unrecognized approximants. Tracing through callers, I see `get_template` explicitly raises on a falsy buffer size, `get_decompressed_waveform` avoids the issue by checking `template_duration` from the table before calling the length function, but `followup_event_significance` would hit a `TypeError` if it received `None` since it adds the length directly into an arithmetic expression.

I want to verify the mode_array string parsing only handles two-character mode strings, and double-check how `maxm` scales `f_lower`—dividing by `maxm` for higher modes extends duration, but there's no guard for `maxm` values below 2, which could actually shorten the frequency unexpectedly. I also want to confirm that `get_hm_length_in_time` correctly threads the modified `f_lower` through to the IMR duration calculation, and that the bank conversion logic subtracts premerger duration from `template_duration` only when `f_final` is present.

There's also a subtle dtype bug where `np.zeros_like(template_ids)` inherits an integer type, and I should confirm the duration lookup properly falls back to the stored `template_duration` column when available rather than recomputing. This wraps up my review—time to finalize the answer.

Below is my full analysis. I made no edits — the repo is untouched (read-only inspection only).

## The one function behind all of it

`_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` at `pycbc/pnutils.py:527`, exported four lines later as

```
get_imr_duration = numpy.vectorize(_get_imr_duration)      # pnutils.py:561
```

It is a flat `if/elif` ladder over exactly six literal spellings — `"SEOBNRv2"`, `'IMRPhenomXAS'`, `"IMRPhenomD"`, `"SEOBNRv4"`, `'SEOBNRv5_ROM'`, and `'SPAtmplt' or 'TaylorF2'` — each delegating to a LAL routine (`SimIMRSEOBNRv2ChirpTimeSingleSpin`, `SimIMRPhenomXASDuration`, `SimIMRPhenomDChirpTime`, `SimIMRSEOBNRv4ROMTimeOfFrequency`, `SimIMRSEOBNRv5ROMTimeOfFrequency`, `SimInspiralTaylorF2ReducedSpinChirpTime`), with a terminal `else: raise RuntimeError("I can't calculate a duration for %s" % approximant)` at line 556.

## Why the reported duration is a constant fraction longer than LAL's

Line 559, *outside* every branch, after the ladder has already produced `time_length`:

```
    return time_length * 1.1
```

That bare, undocumented 10 % pad is applied to whatever LAL returned — every family, every mass range, every spin, every `f_low`. That is your "constant fraction": exactly 1.1×, never family-specific, and completely invisible from any call site. Every consumer inherits it silently: `get_imr_length` (`pycbc/waveform/waveform.py:1012`), hence `seobnrv2/v4/v5_length_in_time` and `imrphenomd_length_in_time` (1023–1041), hence the `_filter_time_lengths` registry (1085–1111), hence `FilterBank.get_template` (`waveform/bank.py:599`), `bank_conversions.get_bank_property` (`tmpltbank/bank_conversions.py:111,119`), `events/coinc.background_bin_from_string` (`events/coinc.py:117`), `events/triggers.get_param` (`events/triggers.py:134`), `bin/plotting/pycbc_page_sensitivity:153` and `bin/plotting/pycbc_plot_bank_corner`. It is meant as a safety margin for filter-buffer sizing, but it leaks into everything that is *reported* as a duration, including the `template_duration` column written by `pycbc_aligned_bank_cat` (`tmpltbank/bank_output_utils.py:329`).

Note the asymmetry that makes this hard to spot: the other length estimator, `spa_length_in_time` → `findchirp_chirptime` (`pycbc/waveform/spa_tmplt.py:33–98`), is pure PyCBC PN and carries **no** 1.1 factor — unless you route `SPAtmplt`/`TaylorF2` through `_get_imr_duration`, in which case you get LAL's reduced-spin chirp time *with* the pad. So the same nominal approximant can yield two different numbers depending on which path is taken.

## What disguises the search: two naming layers that don't agree

`get_waveform_filter_length_in_time(approximant, template=None, **kwargs)` (`waveform.py:1387`) is a pure dictionary lookup into `_filter_time_lengths`, which maps ~28 approximant spellings onto a handful of thin wrappers (1085–1111). Those wrappers then hand a *different*, much smaller vocabulary down to `_get_imr_duration`: `SEOBNRv4_ROM`, `SEOBNRv4`, `SEOBNRv4P` all become the string `"SEOBNRv4"`; `IMRPhenomC`, `IMRPhenomPv2`, `IMRPhenomD_NRTidal`, `IMRPhenomPv2_NRTidal` all become `"IMRPhenomD"`. So the name you configure is never the name that reaches the ladder, and grepping for your approximant lands in the registry, not in the function that actually refuses it. `events/coinc.py:40–44` has to keep a hand-written `_APPROXIMANT_DURATION_MAP` (`'SEOBNRv5duration' -> 'SEOBNRv5_ROM'`) purely to bridge the two conventions — evidence that the mismatch is a known irritant. `td_fd_waveform_transform` (`waveform.py:1136–1166`) and `plugin.add_length_estimator` (`waveform/plugin.py:68–72`) then inject further synthetic names (`X_INTERP`, `SpinTaylorF2_SWAPPER`) into the registry at import time, widening layer 1 without touching layer 2.

## Why a barely different spelling fails while the spelling is fine

Two distinct mechanisms:

1. **Registry miss.** `IMRPhenomXAS` is understood by `_get_imr_duration` (line 535) and by `get_final_freq` (`pnutils.py:447`), but it has **no** entry in `_filter_time_lengths`. `get_waveform_filter_length_in_time` therefore returns `None` for it — a computable name turned away purely by the configuration table. Same for bare `SEOBNRv5` (only `SEOBNRv5_ROM` is registered) and for the many `SEOBNRv5*`/`IMRPhenomX*` variants LAL can actually handle.

2. **Bytes vs. str.** HDF5 bank files store `approximant` as an encoded string (`bank_output_utils.py:320–323` does `approximant.encode()`), so a raw `bank['approximant'][:]` read yields `bytes`. In Python 3, `b'SEOBNRv4' == "SEOBNRv4"` is `False`, so a *perfectly correct* name falls straight through the ladder to the `RuntimeError`. The error text even prints `b'SEOBNRv4'`, which reads as a typo but is a type mismatch. `TemplateBank.approximant()` (`waveform/bank.py:453–456`) explicitly guards this with `if hasattr(apx, 'decode'): apx = apx.decode()`; `bank_conversions.get_bank_property` (line 104–107) does **not** — it passes `bank['approximant'][:][template_ids]` through untouched — and `filter/matchedfilter.followup_event_significance:1810` passes `tmplt['approximant']` raw as well.

## Why one caller survives the refusal

`get_waveform_filter_length_in_time` does not raise; it returns `None` (line 1394–1395). What happens next is entirely up to the caller:

- `FilterBank.get_template` (`bank.py:599–601`) checks `if not buff_size: raise RuntimeError('Template waveform %s not recognized!')` — it converts the silent `None` into a loud failure.
- `get_decompressed_waveform` (`bank.py:719–728`) is the survivor: it reads `self.table[index].template_duration` first and only calls the length estimator when that attribute is absent or `0.0`. For a bank that already carries a `template_duration` column, the unknown-name path is never reached, so the same approximant that kills `get_template` is harmless here.
- `followup_event_significance` (`matchedfilter.py:1810,1834`) would propagate `None` into `int(lookback + 2.0 * trim_pad + length_in_time)` and die with a `TypeError` far from the cause.
- `get_waveform_filter` (`waveform.py:1186,1193`) would quietly stamp `chirp_length = None` onto the returned series.

So "survival" is not a property of the refusal, it is a property of whether the caller happens to have a cached duration or a truthiness check in front of it.

## Why one bad row stops a whole column

`get_imr_duration` is `numpy.vectorize(_get_imr_duration)`. `numpy.vectorize` gives no per-element error containment — it evaluates the first element eagerly to infer the output dtype and then loops; the first `RuntimeError` from any single row unwinds the entire call. In `bank_conversions.get_bank_property` (lines 109–122) the whole bank is passed in one shot:

```
fullband_dur = pnutils.get_imr_duration(*[bank[k][:][template_ids] for k in imr_args + ['f_lower']], **kwargs)
```

with `kwargs = {'approximant': bank['approximant'][:][template_ids]}` — an *array* of names, so vectorize broadcasts over approximants too. One template whose approximant string isn't one of the six literals (or is bytes) aborts the call, and the exception propagates untouched through `get_bank_property` to `bin/plotting/pycbc_plot_bank_corner:185`, `events/cuts.py:439`, and `population/live_pastro.py:74`. There is no NaN fill, no skip, no partial result: the `template_duration` / `premerger_duration` column for *every* template is lost, and the message names only the offending string — no row index, no mass, nothing to locate it with.

A second, quieter defect sits in the same block: when `premerger_duration` is requested but the bank has no `f_final`, line 125 does `prem_dur = np.zeros_like(template_ids)`. `template_ids` is an *integer index* array, so this yields integer zeros, and the subsequent `values -= prem_dur` (line 131) / `values = prem_dur` (133) silently degrades the dtype of a float duration column.

## Why extra-mode waveforms report longer durations

`get_hm_length_in_time(lor_approx, maxm_default, **kwargs)` (`waveform.py:1057–1067`), reached via `imrphenomhm_length_in_time` (→ `"IMRPhenomD"`, default 4) and `seobnrv4hm_length_in_time` (→ `'SEOBNRv4'`, default 5), registered for `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXHM`, `IMRPhenomXPHM`, `SEOBNRv4HM_ROM`.

- **Symbol mechanism.** `parse_mode_array` (`waveform.py:395–421`) normalises whatever `mode_array` arrived — space-separated `"22 33"`, a bare int `22`, a float, or `(l, m)` tuples — by stringifying scalars and splitting two-character strings via `l, m = ma`. It is also invoked unconditionally inside `props` (line 435), so the same normalisation happens for template-derived parameters. Note it only handles 2-character mode strings; anything else (a three-digit `l≥10` mode) would fail to unpack.
- **Branch.** `if 'mode_array' in kwargs and kwargs['mode_array'] is not None: maxm = max(m for _, m in kwargs['mode_array'])` — the max is taken over **m only**, `l` is discarded — `else: maxm = maxm_default` (4 or 5). `f_lower` is required and raises `ValueError("must provide a f_lower")` if absent.
- **Values.** `kwargs['f_lower'] = flow * 2./maxm`, then `get_imr_length(lor_approx, **kwargs)`.

That rescale is the whole story: the m-th harmonic sweeps through a given frequency earlier than the (2,2), so to bound the full multi-mode waveform the estimator asks the *dominant-mode* LAL routine for the duration starting at the lower frequency `2*f_lower/m`. For `maxm=4` that halves the start frequency, and chirp time scales roughly as `f^(-8/3)`, so the reported duration grows by a large factor — not a bug per se, but it stacks multiplicatively on top of the 1.1 pad, and it is applied even when the caller supplied no `mode_array` at all (the defaults 4 and 5 are assumed unconditionally). Because `maxm` ignores `l`, a mode set like `[(3,2),(4,2)]` is treated as m=2 and gets no lengthening.

## Summary of where the numbers come from

Three independent inflations, none documented at the call sites: the unconditional `* 1.1` at `pnutils.py:559`; the `f_lower * 2./maxm` rescale at `waveform.py:1066`; and, for `SPAtmplt`/`TaylorF2`, the possibility of the un-padded `findchirp_chirptime` path instead. Two independent naming layers (`_filter_time_lengths` keys vs. the six `_get_imr_duration` literals) explain why correct-looking names are refused, and `numpy.vectorize` explains why one refused row destroys an entire column.

If a fix were wanted (I have not made one), the minimal, separable changes would be: (a) move the 1.1 margin out of `_get_imr_duration` and into the buffer-sizing callers that actually need padding, or make it an explicit keyword; (b) normalise/decode the approximant in `bank_conversions.get_bank_property` and `followup_event_significance` the way `TemplateBank.approximant` already does; (c) replace the `numpy.vectorize` call in `get_bank_property` with a loop that fills NaN and logs the offending template index; (d) register the missing but computable names (`IMRPhenomXAS`, bare `SEOBNRv5`) in `_filter_time_lengths`; and (e) make `prem_dur` on line 125 `np.zeros(len(template_ids), dtype=float)`.