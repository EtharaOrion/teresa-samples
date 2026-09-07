I've finished the investigation. Everything traces back to one function; here is the full account.

## The one function

`pycbc/pnutils.py`, lines 527–559: `_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")`. Everything in the codebase that reports a template duration ends up here — there is no second implementation.

Its body is a flat `if/elif` chain that dispatches on the approximant string and assigns `time_length` from a LAL call: `SimIMRSEOBNRv2ChirpTimeSingleSpin` for `"SEOBNRv2"`, `SimIMRPhenomXASDuration` for `'IMRPhenomXAS'`, `SimIMRPhenomDChirpTime` for `"IMRPhenomD"`, `SimIMRSEOBNRv4ROMTimeOfFrequency` for `"SEOBNRv4"`, `SimIMRSEOBNRv5ROMTimeOfFrequency` for `'SEOBNRv5_ROM'`, and `SimInspiralTaylorF2ReducedSpinChirpTime` for `'SPAtmplt'`/`'TaylorF2'`; anything else hits `else: raise RuntimeError("I can't calculate a duration for %s" % approximant)` at line 556.

## Why every family and every mass reads long by the same fraction

Line 559 — the last line, after the chain, separated from it by two blank lines — is:

```
    return time_length * 1.1
```

That is the whole explanation. It is a flat 10 % safety pad applied on the common exit path, so it multiplies *every* branch: EOB, Phenom and the reduced-spin PN branch alike, at every mass and spin. Because it is multiplicative rather than additive, the excess over the LAL figure is a constant *fraction*, exactly matching the symptom, and it never washes out at high or low mass.

Three things disguise it. First, position: it sits below the dispatch chain, so a reader checking "which LAL call does SEOBNRv4 use" reads the branch and stops before reaching it. Second, the function carries an empty docstring (`""` — as do `frequency_cutoff_from_name` and `get_inspiral_tf` in the same file), so the pad is documented nowhere; the contract "this returns a padded bound, not a physical duration" exists only in that one token. Third, indirection: the name callers import is not this function but `get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561), and above *that* sit `get_imr_length` and the `*_length_in_time` shims in `pycbc/waveform/waveform.py` (lines 1012–1041) and the `_filter_time_lengths` registry, so most call sites are three or four hops from the multiplication. The intent is legitimate — these values size filter buffers (`bank.get_template`, `pycbc_live`, `followup_event_significance`), where over-estimating is safe and under-estimating is fatal — but the same padded number is also written to disk as the `template_duration` column (`pycbc/tmpltbank/bank_output_utils.py:329–335`) and used as a physics-like binning/cut variable, which is where it reads as "wrong".

## Why configuration turns away names it could compute

The dispatch is exact string equality against six literals. There is no normalisation, no case folding, no `.decode()`, no alias table. So `'SEOBNRv5'` fails while `'SEOBNRv5_ROM'` succeeds; `'SEOBNRv4_ROM'`, `'IMRPhenomPv2'`, `'IMRPhenomXPHM'`, `'IMRPhenomD_NRTidal'` all fail even though a perfectly good dominant-mode surrogate exists for each; and a bytes value read straight out of an HDF5 bank (`b'SEOBNRv4'`) never equals the `str` literal and falls to the `RuntimeError`.

The contrast inside the same file is sharp. `get_final_freq` (line 447) collapses `'IMRPhenomD'` and `'IMRPhenomXAS'` onto one cutoff and maps bare `'SEOBNRv5'`; `get_inspiral_tf` (line 597) is even more forgiving, slicing `approximant[:len('SEOBNRv*')]` so any `SEOBNRv*` variant resolves by prefix. Only the duration routine insists on the literal spelling. Callers therefore have to carry private translation dictionaries to compensate: `_APPROXIMANT_DURATION_MAP` in `pycbc/events/coinc.py:40–44` exists purely to turn `'SEOBNRv5duration'` into `'SEOBNRv5_ROM'`, and `pycbc/events/triggers.py:132–133` defaults a missing approximant to the string `"SEOBNRv4"`.

That same narrowing shows up as vocabulary asymmetry: `background_bin_from_string` accepts three duration labels (`SEOBNRv2/v4/v5duration`) and only two frequency labels (`'SEOBNRv2Peak'`, `'SEOBNRv4Peak'`, line 107) even though `named_frequency_cutoffs` defines eleven — including `SEOBNRv5RD`/`SEOBNRv5Peak`. A bin string naming a cutoff the library can compute is rejected by `raise ValueError('Invalid bin type %s')` at line 127 because the caller's hard-coded list, not the library, is the gate.

## Why one caller survives the refusal

There are two different failure modes, and which one you get depends on which layer you enter through.

`pycbc/waveform/waveform.py:1387` `get_waveform_filter_length_in_time` looks the approximant up in `_filter_time_lengths` and, on a miss, returns `None` rather than raising. Crucially, that registry (lines 1085–1111) is itself the alias table pnutils lacks: `"SEOBNRv4P"` and `"SEOBNRv4_ROM"` both map to `seobnrv4_length_in_time`, `"IMRPhenomPv2"`, `"IMRPhenomC"` and the NRTidal variants map to `imrphenomd_length_in_time`, and `td_fd_waveform_transform` (line 1136) clones every entry to an `_INTERP` twin. So a template labelled `IMRPhenomPv2` survives: the registry rewrites it to `IMRPhenomD` before pnutils ever sees it.

`pycbc/tmpltbank/bank_conversions.py:111` and `:119` bypass that layer entirely — `get_bank_property` calls `pnutils.get_imr_duration` directly, forwarding the bank's raw `approximant` column (line 105). The identical bank that filters fine through `bank.get_template` raises `RuntimeError` here, because the alias translation lived one layer up and was skipped. That is the asymmetry you are seeing.

Among the users of the `None`-returning layer, survival is a matter of whether the caller checks. `pycbc/waveform/bank.py:601` guards with `if not buff_size: raise RuntimeError('Template waveform %s not recognized!')` and fails loudly and legibly. `pycbc/filter/matchedfilter.py:1811` does not check: `length_in_time` flows straight into `bdur = int(lookback + 2.0 * trim_pad + length_in_time)` at line 1835 and dies with an opaque `TypeError` on `None`. `bin/pycbc_live:320` is likewise unguarded. Note also that `if not buff_size` conflates `None` with a legitimate `0.0`.

## Why one bad row stops a whole column

`get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561). `numpy.vectorize` is a Python-level loop over elements with no per-element error handling, so the first element that raises propagates out of the entire call — you do not get a partial array or a NaN in one slot, you get nothing.

`get_bank_property` makes this maximally destructive because it passes the approximant as an *array* (`kwargs = {'approximant': bank['approximant'][:][template_ids]}`) to be broadcast alongside the mass and spin arrays. One template row out of a million carrying an unrecognised or byte-typed approximant string aborts the whole `fullband_dur` computation, and with it the entire duration column — killing `bin/pycbc_plot_bank_corner:185`, the `live_pastro` histogram in `pycbc/population/live_pastro.py:74`, and any `--template-cuts` on duration routed through `pycbc/events/cuts.py:439`. `vectorize` also fixes the output dtype from the first call's return, another latent single-row hazard on the same path.

Worth noting for the premerger case: `get_bank_property` computes `fullband_dur` and `prem_dur` by two separate `get_imr_duration` calls and takes the difference (`values = fullband_dur; values -= prem_dur`). Both terms carry the 1.1 factor, so it does not cancel — it scales the difference too.

## Why the extra-mode figures come out longer

Not a bug; a deliberate frequency substitution driven by the mode symbols. `get_hm_length_in_time(lor_approx, maxm_default, **kwargs)` at `pycbc/waveform/waveform.py:1057` runs `kwargs = parse_mode_array(kwargs)`, takes `maxm = max(m for _, m in kwargs['mode_array'])` when a mode array is present and `maxm_default` otherwise, then rewrites `kwargs['f_lower'] = flow * 2./maxm` before delegating to the *dominant-mode* approximant via `get_imr_length`.

The physics: an (ℓ, m) mode radiates at roughly m/2 times the orbital-quadrupole frequency, so a mode with m > 2 enters the band earlier than the 22 mode. To bound the full multimode waveform using only a 22-mode duration model, you ask that model how long it takes starting from the *lower* frequency `f_low · 2/m_max`. The result is legitimately longer, and it is not a fixed offset — it depends on which modes are requested.

The magnitudes: `imrphenomhm_length_in_time` (line 1043) passes `("IMRPhenomD", 4)`, so `IMRPhenomHM`, `IMRPhenomPv3HM`, `IMRPhenomXHM` and `IMRPhenomXPHM` all default to `f_low/2`; `seobnrv4hm_length_in_time` (line 1050) passes `('SEOBNRv4', 5)`, so `SEOBNRv4HM_ROM` defaults to `f_low · 0.4`. The mode-symbol parsing is in `parse_mode_array` (line 395), which normalises `'32'`, `32` and `[3, 2]` into `(3, 2)` tuples so the `max(...)` over `m` works. This path also has its own key-error dialect: a missing `f_lower` becomes `ValueError("must provide a f_lower")` here, whereas the plain `get_imr_length` would surface a `KeyError`.

And of course the 1.1 rides on top of all of it — a higher-mode duration is `1.1 ×` the 22-mode duration evaluated at a reduced starting frequency.

## Summary of the branch/value mechanics

The chain is: caller → `_filter_time_lengths[name]` (alias/HM layer, misses return `None`) → `*_length_in_time` shim → `get_imr_length` (coerces the five floats out of kwargs) → `numpy.vectorize` wrapper → `_get_imr_duration` (exact-match dispatch, `RuntimeError` on miss) → LAL → `× 1.1`. The constant inflation is line 559 of `pycbc/pnutils.py`; the spurious refusals are the literal-equality chain at lines 531–556 plus the absence of an alias/decode step there; the all-or-nothing column failure is `numpy.vectorize` at line 561 combined with array-valued approximants at `bank_conversions.py:105`; and the longer higher-mode figures are the `f_low · 2/maxm` substitution at `waveform.py:1067`.

I made no changes to the repository — this is analysis only. If you want a fix, the minimal shape would be: hoist the alias/normalisation logic (case, `bytes` decoding, `SEOBNRv*` prefix, `_ROM`/`P`/`Pv2` families) into `_get_imr_duration` so both entry paths share it; make the 1.1 pad an explicit, documented, defaulted keyword so buffer-sizing callers opt in and physics/binning callers opt out; and replace `numpy.vectorize` with a loop that records a sentinel per failing row instead of aborting the column.

Everything you observed converges on a single function, plus three surrounding layers that disguise or amplify it. Nothing was edited; below is the whole account.

**The one function: `_get_imr_duration` in `pycbc/pnutils.py`, lines 527–559.**

It is the only implementation of IMR duration in the tree. Its body is an exact-string `if/elif` chain over `approximant`, each branch calling one LAL routine:

- `"SEOBNRv2"` → `SimIMRSEOBNRv2ChirpTimeSingleSpin` (line 533)
- `'IMRPhenomXAS'` → `SimIMRPhenomXASDuration` (536)
- `"IMRPhenomD"` → `SimIMRPhenomDChirpTime` (539)
- `"SEOBNRv4"` → `SimIMRSEOBNRv4ROMTimeOfFrequency` (542)
- `'SEOBNRv5_ROM'` → `SimIMRSEOBNRv5ROMTimeOfFrequency` (546)
- `'SPAtmplt'` or `'TaylorF2'` → `SimInspiralTaylorF2ReducedSpinChirpTime` (552)
- otherwise, line 556: `raise RuntimeError("I can't calculate a duration for %s" % approximant)`

**Why the constant-fraction overshoot.** After the chain, separated from it by two blank lines, line 559 is `return time_length * 1.1`. That is a flat 10% pad on the *common exit path*, so it multiplies every branch — EOB, Phenom, and reduced-spin PN alike — at every mass, spin and starting frequency. Because it is multiplicative rather than additive, the excess over the bare LAL number is a constant fraction that never shrinks at high or low mass, exactly the symptom you describe. What disguises it: it sits below the dispatch chain, so a reader who checks "which LAL call does SEOBNRv4 use?" reads the branch and stops before reaching it; and the function has an empty docstring, so the contract "this is a padded duration, not the waveform duration" is never stated anywhere. `get_imr_duration` (line 561) is a `numpy.vectorize` alias, which adds a further layer between callers and the pad.

**Why one spelling is refused and a barely different one is fine.** The chain compares literal strings. `'SEOBNRv5_ROM'` matches; `'SEOBNRv5'` does not and falls to the `RuntimeError`. There is no aliasing, no prefix matching, no `bytes` decoding inside the function. Callers each carry their own private normalisation, which is why one caller survives a spelling the other rejects: `pycbc/events/coinc.py:40–44` defines `_APPROXIMANT_DURATION_MAP` mapping `'SEOBNRv5duration' → 'SEOBNRv5_ROM'` (and v2/v4 likewise), and `pycbc/events/triggers.py:132–133` substitutes `"SEOBNRv4"` when no approximant is supplied. A caller with a translation table or a default survives; a caller that hands the raw bank string straight through does not. Note also `pycbc/waveform/bank.py:453–455` decodes bytes approximants for the waveform path, but `bank_conversions.py:105` does not decode before the duration call.

**Why fewer duration labels than frequency labels.** In `background_bin_from_string` (`pycbc/events/coinc.py:47`), the duration branch at line 116 accepts only the three keys in `_APPROXIMANT_DURATION_MAP`, while the frequency branch at line 107 hard-codes `['SEOBNRv2Peak', 'SEOBNRv4Peak']`. Meanwhile `named_frequency_cutoffs` in `pnutils.py` defines eleven names, including `SEOBNRv5RD` and `SEOBNRv5Peak`. Anything not in those two literal lists hits `raise ValueError('Invalid bin type %s' % bin_type)` at line 127. So the gate is the caller's hard-coded membership lists, not the library: `pnutils` can compute names the configuration layer refuses to pass on. The same pattern appears in `pycbc/tmpltbank/bank_conversions.py:35` (`conversion_options`) and `pycbc/events/cuts.py:53`, which build the user-visible parameter vocabulary from static lists.

**Why one bad row kills the whole column.** `get_imr_duration = numpy.vectorize(_get_imr_duration)` (line 561). `numpy.vectorize` calls the scalar function per element with no per-element error handling, so a `RuntimeError` on any single row propagates out of the entire array call — you get no output at all, not a partial array or a NaN in one slot. This is worst in `get_bank_property` (`pycbc/tmpltbank/bank_conversions.py:104–121`), which passes the approximant as an *array* (`kwargs = {'approximant': bank['approximant'][:][template_ids]}`) broadcast alongside the masses and spins. One template row with an unrecognised or undecoded approximant aborts the whole `fullband_dur` (and `prem_dur`) computation, taking down every downstream consumer: `bin/plotting/pycbc_plot_bank_corner:185`, `pycbc/population/live_pastro.py:74`, and the template cuts at `pycbc/events/cuts.py:439`. Also worth noting: `get_bank_property` computes `template_duration`/`duration` as `fullband_dur - prem_dur`, two separate `get_imr_duration` calls, so the 1.1 factor appears in both terms and the difference is likewise inflated by 1.1.

**Why extra modes stretch the number, and the mechanism that does it.** `get_hm_length_in_time(lor_approx, maxm_default, **kwargs)` at `pycbc/waveform/waveform.py:1057` calls `parse_mode_array(kwargs)`, then takes `maxm = max(m for _, m in kwargs['mode_array'])` when a mode array is present, else `maxm_default` (4 for `imrphenomhm_length_in_time`, 5 for `seobnrv4hm_length_in_time`). It then rewrites `kwargs['f_lower'] = flow * 2./maxm` (line 1067) and delegates to `get_imr_length(lor_approx, **kwargs)` — i.e. it asks the *dominant-mode* approximant for the duration from a lowered start frequency, because the highest `m` mode reaches a given frequency earlier. For `maxm > 2` that lowered `f_lower` yields a strictly longer duration; for `maxm == 2` it is a no-op. The `try/except KeyError` around `flow` (1063–1066) converts a missing `f_lower` into `ValueError("must provide a f_lower")`, where the plain `get_imr_length` path would surface a raw `KeyError`. And since the HM path ultimately returns through `_get_imr_duration`, the 1.1 pad rides on top: the reported HM length is `1.1 ×` the 22-mode length at the rescaled frequency.

**The reduced chain.** caller → `_filter_time_lengths[name]` (alias/HM layer; a miss makes `get_waveform_filter_length_in_time` at `waveform.py:1387–1395` return `None` rather than raise) → `*_length_in_time` shim → `get_imr_length` (`waveform.py:1012`, coerces five floats out of kwargs) → `numpy.vectorize` wrapper → `_get_imr_duration` (exact-match dispatch, `RuntimeError` on miss) → LAL → `× 1.1`.

Note the two different failure modes at the two lookup layers: the dict miss in `get_waveform_filter_length_in_time` returns `None` silently (which `bank.py:600` then converts into `RuntimeError('Template waveform %s not recognized!')` via `if not buff_size`, but `matchedfilter.py:1811` and `bank_output_utils.py:329` do not check, so a `None` flows into arithmetic there), while the string miss inside `_get_imr_duration` raises.

**Branch/value summary of the three loci that would need attention** (described, not changed): the literal-equality dispatch at `pnutils.py:531–556`; the `numpy.vectorize` at `pnutils.py:561` combined with array-valued approximants from `bank_conversions.py:105`; and the `f_low · 2/maxm` substitution at `waveform.py:1067`. A fix would push alias/normalisation logic (bytes decoding, `SEOBNRv*` prefixes, `_ROM`/`P`/`Pv2` suffixes) into `_get_imr_duration` or a shared resolver, make the 1.1 pad an explicit documented keyword rather than an unconditional tail multiply, and give the vectorised wrapper a per-row sentinel so one unrecognised template does not void the column. I have made none of those edits.