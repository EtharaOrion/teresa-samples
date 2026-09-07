Let me make sure I have all the facts straight, then produce the final answer. I have already gathered:

1. `pycbc/pnutils.py` lines 527-561: `_get_imr_duration` with branches for six exact strings and `return time_length * 1.1`, and `get_imr_duration = numpy.vectorize(_get_imr_duration)`.

2. `pycbc/waveform/waveform.py` lines 1012-1074: `get_imr_length`, `seobnrv2_length_in_time`, `seobnrv4_length_in_time`, `seobnrv5_length_in_time` (passes "SEOBNRv5_ROM"), `imrphenomd_length_in_time`, `imrphenomhm_length_in_time` (get_hm_length_in_time("IMRPhenomD", 4)), `seobnrv4hm_length_in_time` (get_hm_length_in_time('SEOBNRv4', 5)), `get_hm_length_in_time` which does `kwargs['f_lower'] = flow * 2./maxm`.

3. `_filter_time_lengths` registry lines ~1085-1113.

4. `get_waveform_filter_length_in_time` lines 1387-1395 returns None if approximant not in registry.

5. `pycbc/events/coinc.py` `_APPROXIMANT_DURATION_MAP` = {'SEOBNRv2duration': 'SEOBNRv2', 'SEOBNRv4duration': 'SEOBNRv4', 'SEOBNRv5duration': 'SEOBNRv5_ROM'} and `background_bin_from_string`.

6. `pycbc/events/triggers.py::get_param` — 'template_duration' branch: defaults approximant to "SEOBNRv4" if not given, scalar call.

7. `pycbc/tmpltbank/bank_conversions.py::get_bank_property` — uses bank['approximant'] column if present, vectorized call.

I verified with the quick numpy experiment that `np.vectorize` propagates an exception raised by any single row — so one bad approximant string in the bank's `approximant` column kills the whole call (the whole column of values), whereas the scalar caller in triggers.py only substitutes a default and processes one row at a time.

The task says answer in prose, describe rather than fix. I should also note the fix description but not apply.

Now let me write the final answer in prose. The user asked for: "name file one function behind explain what disguises it search, why one caller survives refusal where why one bad row stops a whole column, library theory holds, why configuration turns away computable names, why extra-mode figures a symbols mechanism, branches, values. Answer in prose."

So the answer: file `pycbc/pnutils.py`, function `_get_imr_duration` (vectorized as `get_imr_duration`).

I'll write it fully in prose now.
I have everything I need. Here is the complete analysis, in prose.

## The file and the one function

The whole cluster of symptoms comes from a single function in a single file: **`pycbc/pnutils.py`, `_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` (lines 527–559)**, which is published to the rest of the code base only through the vectorized wrapper on line 561, `get_imr_duration = numpy.vectorize(_get_imr_duration)`. This is the choke point through which PyCBC turns (masses, spins, a starting frequency, and a family name) into "how long is this signal".

## Mechanism: branches and values

The body does two things. First it casts the five numbers with `float(...)` — a coercion that also silently accepts anything numeric-convertible. Then it dispatches on **exact string equality** of `approximant` against a closed list of **six** spellings, each wired to one LALSimulation routine:

- `"SEOBNRv2"` → `SimIMRPhenomBComputeChi`, then `SimIMRSEOBNRv2ChirpTimeSingleSpin`
- `"IMRPhenomXAS"` → `SimIMRPhenomXASDuration`
- `"IMRPhenomD"` → `SimIMRPhenomDChirpTime`
- `"SEOBNRv4"` → `SimIMRSEOBNRv4ROMTimeOfFrequency`
- `"SEOBNRv5_ROM"` → `SimIMRSEOBNRv5ROMTimeOfFrequency`
- `"SPAtmplt"` or `"TaylorF2"` → `SimInspiralTaylorF2ReducedSpinComputeChi`, then `SimInspiralTaylorF2ReducedSpinChirpTime`

Anything else falls to `raise RuntimeError("I can't calculate a duration for %s" % approximant)`. And every branch, without exception, ends in `return time_length * 1.1`.

## Why the reported duration is a constant fraction longer, for every family and mass range

That is literally the last line: `time_length * 1.1`. The LALSimulation routine returns its own figure for the given masses, spins and starting frequency, and PyCBC multiplies it by 1.10 unconditionally. The multiplier sits *after* the `if/elif` chain, so it applies identically to SEOBNRv2, IMRPhenomD, IMRPhenomXAS, SEOBNRv4, SEOBNRv5_ROM and TaylorF2/SPAtmplt alike, and it is independent of mass, spin and `f_low`. It is a deliberate safety margin (the generated waveform is slightly longer than the analytic chirp time, and the caller wants a buffer), not something the underlying library reports — which is exactly why the mismatch is a clean constant +10% rather than a growing or family-dependent discrepancy.

## Why a barely different spelling of a family name fails, and why that is the library "refusing an unknown name"

The dispatch is a chain of literal-string comparisons, so a one-character difference is a different key, and there is no fallback. `SEOBNRv4` is recognized but `SEOBNRv4P`, `SEOBNRv4_ROM`, `SEOBNRv4HM_ROM`, `SEOBNRv4T` are not; `SEOBNRv5_ROM` is recognized but `SEOBNRv5` is not; `IMRPhenomD` is recognized but `IMRPhenomPv2`, `IMRPhenomXPHM`, `IMRPhenomD_NRTidal` are not. The failure surfaces as `RuntimeError("I can't calculate a duration for %s")` — the message an unknown-name refusal produces. Note the asymmetry with the *waveform generator* side: the generator's registries (`cpu_td`/`cpu_fd` in `pycbc/waveform/waveform.py`, built by enumerating `lalsim.GetStringFromApproximant(...)` over everything LALSimulation implements) accept dozens of families. So a name that generates fine can still be un-duratable: duration support was only ever hand-wired for those six spellings.

## The frequency-versus-duration label mismatch ("takes duration labels as frequency ones")

The same file, `pnutils.py`, keeps two parallel hand-maintained lookup tables that are *almost* consistent but use different keys: the duration dispatch above, and `tof_func_map` in `get_inspiral_tf` (around lines 600–605), keyed `'SEOBNRv2'`, `'SEOBNRv4'`, `'SEOBNRv5'` — note `SEOBNRv5` *without* the `_ROM` suffix there, versus `SEOBNRv5_ROM` in the duration function. So two call sites that appear to speak the same vocabulary actually use two slightly different spellings for the same family, and `get_final_freq` (line 449) uses `'SEOBNRv5'` too. A caller that grabs a label valid in one table and feeds it to the other gets the unknown-name refusal even though the value is perfectly computable. That is the disguise: the bug looks like a missing model, but it is a name-resolution problem between tables that were never unified.

## Why one caller survives the refusal, and why one bad row stops a whole column

There are two very different callers, and they fail differently.

**The caller that survives** is `pycbc/events/triggers.py::get_param` (lines 131–136):

```python
elif par == 'template_duration':
    if not args.approximant:
        args.approximant = "SEOBNRv4"
    parvals = pnutils.get_imr_duration(m1, m2, s1z, s2z,
                                       args.f_lower, args.approximant)
```

It works one template at a time, with a *scalar* approximant taken from the command line, and it substitutes a default (`SEOBNRv4`) when none was given. So it can never hit the unknown-name branch unless the user explicitly types an unsupported name, and a failure affects a single template rather than everything.

**The caller where one bad row stops a whole column** is `pycbc/tmpltbank/bank_conversions.py::get_bank_property` (lines 87–135), reached from `pycbc/events/cuts.py` (line 437), `pycbc/population/live_pastro.py` (line 74), and `bin/plotting/pycbc_plot_bank_corner` (line 185). It reads an `approximant` **column** out of the bank file when one exists, and calls the vectorized `get_imr_duration` over the whole array of rows at once. Because `numpy.vectorize` applies the scalar function row by row and **propagates the first exception**, a single row whose `approximant` string is not one of the six recognized spellings raises out of the vectorized call and aborts the entire computation — one bad row destroys the whole column of durations, and with it the cut, the binning, or the corner plot that asked for it. (I confirmed this propagation behavior with a small `numpy.vectorize` experiment.) The third caller, `pycbc/events/coinc.py::background_bin_from_string` (lines 40–46, 113–115), is protected only by its private translation table `_APPROXIMANT_DURATION_MAP = {'SEOBNRv2duration': 'SEOBNRv2', 'SEOBNRv4duration': 'SEOBNRv4', 'SEOBNRv5duration': 'SEOBNRv5_ROM'}`, which silently rewrites the user-facing label into the spelling the duration function wants — which is precisely why `SEOBNRv5duration` works there while a bare `SEOBNRv5` would not elsewhere.

## Why configuration turns away computable names

The user-facing configuration layer (`--bank-bins`, `--template-cuts`, the conversion options list `conversion_options` in `bank_conversions.py`, which includes `'duration'`, `'template_duration'`, `'premerger_duration'`) happily accepts `<Family>duration`-style names and passes the family part straight down to `_get_imr_duration`. Since that function only knows six spellings, the configuration effectively rejects — with a `RuntimeError` — families that LALSimulation can perfectly well time (e.g. `IMRPhenomPv2`, `SEOBNRv4P`, `SEOBNRv4HM`, `IMRPhenomXPHM`). The value is computable; the label the configuration accepts is simply not the label the duration function recognizes, and the only bridge is a three-entry hand-maintained table in `coinc.py` that most callers never see. When `get_bank_property` cannot use a stored `template_duration` column and must compute one, the refusal propagates up as a hard error.

## Why extra-mode waveforms report longer durations, via the symbols mechanism

Higher-mode families get longer durations through a **symbols mechanism**: the harmonic index ℓ, not the family name. In `pycbc/waveform/waveform.py` (lines 1043–1074), `imrphenomhm_length_in_time` and `seobnrv4hm_length_in_time` both funnel into `get_hm_length_in_time(lor_approx, maxm_default, **kwargs)`, which does:

```python
maxm = max(m for _, m in kwargs['mode_array'])   # if a mode_array was given
kwargs['f_lower'] = flow * 2. / maxm
return get_imr_length(lor_approx, **kwargs)
```

Because the ℓ=m harmonic's dominant GW frequency is m/2 times the (2,2) frequency, an ℓ-max mode effectively "starts" at a lower (2,2)-equivalent frequency — `2/maxm` times the nominal one — and therefore chirps for longer. A larger `maxm` gives a smaller multiplier and hence a *longer* duration; the 1.1 fudge is then applied on top. The registry binds this to `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXPHM` (default `maxm = 4`) and `SEOBNRv4HM_ROM` (default `maxm = 5`) in `_filter_time_lengths` (lines ~1085–1113). Note the side effect worth flagging: `get_hm_length_in_time` **mutates** `kwargs['f_lower']` in place rather than copying, so the caller's dictionary comes back with a modified `f_lower`.

## Library theory holds

None of this contradicts LALSimulation. Each LALSimulation routine returns a well-defined figure for the masses, spins and frequency it is handed, and PyCBC then (a) multiplies it by a fixed 1.1, or (b) hands it a *lowered* frequency (`flow * 2/maxm`) that mechanically yields a longer time, or (c) refuses the name outright because it never mapped that spelling. The apparent anomalies — constant overestimate, family-name fragility, column-wide aborts, extra-mode inflation — are all introduced on the PyCBC side of the boundary, in `_get_imr_duration` and its three callers.

## Where each symptom lives, summarized

- Constant +10%: `pycbc/pnutils.py:559` (`return time_length * 1.1`), applied after every branch.
- Unknown-name refusal: `pycbc/pnutils.py:556` (`raise RuntimeError(...)`), caused by the six-literal `if/elif` chain at 535–554.
- Duration-vs-frequency label drift: duration table keyed `SEOBNRv5_ROM` (`pnutils.py:545`) versus `tof_func_map`/`get_final_freq` keyed `SEOBNRv5` (`pnutils.py:449, 604`).
- Caller that survives: `pycbc/events/triggers.py:131–136` (scalar, default-substituting).
- One bad row kills a column: `pycbc/tmpltbank/bank_conversions.py:104–135` feeding a vectorized `get_imr_duration` (`pnutils.py:561`), with exception propagation inherent to `numpy.vectorize`.
- Configuration refusing computable names: the same path, plus `pycbc/events/coinc.py:40–46` `_APPROXIMANT_DURATION_MAP` as the only, partial, bridge.
- Extra modes longer: `pycbc/waveform/waveform.py:1055–1074` (`get_hm_length_in_time`, `f_lower = flow * 2./maxm`) and its registrations at 1085–1113.
- Soft fallback for unknown families in filtering: `get_waveform_filter_length_in_time` (`waveform.py:1387–1395`) returns `None` when the approximant is absent from `_filter_time_lengths` — a silent alternative to the hard `RuntimeError`.

If a fix were ever wanted (I have made none), the natural shape would be: unify the approximant spellings into a single shared mapping, make the six-entry dispatch fall back on a general LALSimulation call instead of raising, and have the vectorized callers isolate per-row failures rather than aborting the column — but per the task, this is analysis only and no files were modified.

Identified pycbc/pnutils.py::_get_imr_duration (lines 527-559, exported as numpy.vectorize'd get_imr_duration at line 561) as the single function behind all reported symptoms, and explained in prose: (1) the constant +10% overestimate is the unconditional `time_length * 1.1` applied after every branch; (2) near-miss family names fail because dispatch is exact string equality over only six spellings (SEOBNRv2, IMRPhenomXAS, IMRPhenomD, SEOBNRv4, SEOBNRv5_ROM, SPAtmplt/TaylorF2), producing RuntimeError "I can't calculate a duration for %s"; (3) duration vs frequency label drift between pnutils tables (SEOBNRv5_ROM vs SEOBNRv5); (4) pycbc/events/triggers.py::get_param survives because it is scalar and defaults to SEOBNRv4, while pycbc/tmpltbank/bank_conversions.py::get_bank_property vectorizes over a bank approximant column so one bad row aborts the whole column via numpy.vectorize exception propagation; (5) extra-mode families report longer durations because get_hm_length_in_time (waveform.py 1055-1074) lowers f_lower by 2/maxm based on the mode_array symbols. No files were created, edited, or deleted.