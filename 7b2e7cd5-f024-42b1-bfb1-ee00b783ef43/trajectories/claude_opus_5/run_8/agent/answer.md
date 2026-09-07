I've reconfirmed the key details in waveform.py and bank.py, so I'm ready to write the final answer covering the mode_array parsing limitation, get_hm_length_in_time behavior, and the one-caller-survives-refusal claim.

I investigated read-only; the working tree is untouched (`git status --porcelain` is empty, no edits, no new files).

## The one function behind all four symptoms

`_get_imr_duration` in **`pycbc/pnutils.py`, lines 527–559**, wrapped on line 561 as `get_imr_duration = numpy.vectorize(_get_imr_duration)`.

### 1. Why the duration is a constant fraction longer than the wave library's figure

Every branch of the function asks lalsimulation for a duration and stores it in `time_length`:

- `SimIMRSEOBNRv2ChirpTimeSingleSpin` (SEOBNRv2, line 533)
- `SimIMRPhenomXASDuration` (IMRPhenomXAS, 536)
- `SimIMRPhenomDChirpTime` (IMRPhenomD, 539)
- `SimIMRSEOBNRv4ROMTimeOfFrequency` (SEOBNRv4, 543)
- `SimIMRSEOBNRv5ROMTimeOfFrequency` (SEOBNRv5_ROM, 546)
- `SimInspiralTaylorF2ReducedSpinChirpTime` (SPAtmplt/TaylorF2, 552)

Then line 559 returns `time_length * 1.1`, unconditionally, after the branch has closed. That is the whole explanation for "a constant fraction longer, across every family and mass range": it is not a modelling difference, a spin convention, or an `f_lower` mismatch — it is a flat 10% safety pad applied to whatever the library returned. It is disguised because it sits one blank-line gap below the `else: raise`, outside all the branch bodies, so reading any single branch gives you the impression that the library value is returned verbatim. There is no comment or docstring explaining it (`ast.get_docstring` returns an empty string), so the pad has no visible justification in the source.

The pad is defensible for its original purpose: `get_imr_duration` feeds template-buffer sizing in `pycbc/waveform/bank.py:599` and `pycbc/filter/matchedfilter.py:1811`, where under-allocating truncates a template but over-allocating merely wastes memory. The theory holds there. What it is not is a physical duration, and it leaks into places that report it as one: `pycbc/tmpltbank/bank_output_utils.py:329` writes it into the bank's `template_duration` column, `pycbc/tmpltbank/bank_conversions.py:111/119` recomputes it for plots and cuts, `pycbc/events/triggers.py:134` uses it as a binning parameter, and `bin/plotting/pycbc_page_sensitivity:153` plots it. There is also an inconsistency worth flagging: `bank_conversions.get_bank_property` line 90 returns the stored `template_duration` column when present and only otherwise recomputes it, so the same request can yield two answers 10% apart depending on which columns a bank file happens to carry — but since the stored column was itself written through the same padded path, both are padded; the real hazard is a bank whose `template_duration` came from elsewhere.

### 2. Why a barely different spelling of a family's name fails while a similar spelling is fine

`_get_imr_duration` dispatches by exact string equality against exactly six spellings: `"SEOBNRv2"`, `'IMRPhenomXAS'`, `"IMRPhenomD"`, `"SEOBNRv4"`, `'SEOBNRv5_ROM'`, and `'SPAtmplt'`/`'TaylorF2'`. Anything else hits `else: raise RuntimeError("I can't calculate a duration for %s" % approximant)`.

The reason a near-identical name survives is the indirection layer in `pycbc/waveform/waveform.py`. `_filter_time_lengths` (lines 1085–1112) maps 27 approximant names onto a handful of small adapters — `seobnrv2_length_in_time`, `seobnrv4_length_in_time`, `seobnrv5_length_in_time`, `imrphenomd_length_in_time`, `spa_length_in_time`, plus the HM ones — and each adapter calls `get_imr_length(<one of the six canonical names>, **kwds)` (lines 1012–1041). So `SEOBNRv4_ROM`, `SEOBNRv4P`, `IMRPhenomPv2`, `IMRPhenomC`, `IMRPhenomD_NRTidal`, `SpinTaylorF2`, `SpinTaylorT5` and friends all work — not because `_get_imr_duration` knows them, but because the table rewrites them to a name it does know. Note the asymmetry: `IMRPhenomXAS` is a valid key in `_get_imr_duration` but is absent from `_filter_time_lengths`, while `SEOBNRv4_ROM` is a valid `_filter_time_lengths` key but not a valid `_get_imr_duration` name. Which spelling works depends entirely on which door you come in through.

Callers that go through `_filter_time_lengths` (bank sizing, `followup_event_significance`, `find_variable_start_frequency`) get the translation. Callers that call `pnutils.get_imr_duration` directly with a raw string — `bank_conversions.py:111/119`, `events/coinc.py:117`, `events/triggers.py:134`, `pycbc_page_sensitivity` — do not, and are exposed to the raw six-name vocabulary. `events/coinc.py` acknowledges this with its own `_APPROXIMANT_DURATION_MAP` (lines 40–44) translating `SEOBNRv5duration` → `SEOBNRv5_ROM`; the other three direct callers have no such map. `events/triggers.py:132–133` sidesteps it by forcing `args.approximant = "SEOBNRv4"` when unset.

A second, subtler spelling trap: `bank_conversions.py:104–105` reads `bank['approximant'][:][template_ids]` straight out of HDF5 and passes it through. `bank_output_utils.py:321–323` writes that column as *bytes* (`approximant.encode()`), and `TemplateBank.approximant()` in `bank.py:453–455` is the only place that calls `.decode()`. I confirmed with numpy that `b'SEOBNRv4' == 'SEOBNRv4'` is `False`, so a bytes-valued column reaching `_get_imr_duration` falls through every branch and raises `RuntimeError: I can't calculate a duration for b'SEOBNRv4'` for a name that is spelled perfectly.

### 3. Why one caller survives the refusal where others do not, and why one bad row kills a whole column

There are two refusal mechanisms stacked on top of each other with opposite temperaments:

- `get_waveform_filter_length_in_time` (`waveform.py:1387–1395`) is **soft**: an unknown approximant is not an error, it is `return None`.
- `_get_imr_duration` is **hard**: an unknown approximant raises.

Because the soft layer checks table membership *before* it can ever reach the hard layer, the two never actually disagree in practice — the `RuntimeError` is unreachable via `get_waveform_filter_length_in_time`, and what escapes is a silent `None`.

How each caller handles that `None` decides its fate:

- `bank.get_template` (`bank.py:599–601`) checks `if not buff_size: raise RuntimeError('Template waveform %s not recognized!')`. That is the one caller that converts the silence into a clean, attributable failure.
- `td_waveform_to_fd_waveform`'s caller path at `waveform.py:778–779` pre-checks membership and raises `ValueError("Approximant %s does not have a _filter_time_lengths function")` before calling — it survives by never asking.
- `get_decompressed_waveform` (`bank.py:725–728`) accepts the `None` and assigns it to `hdecomp.chirp_length` and `hdecomp.length_in_time`; the failure surfaces much later, somewhere else, as an arithmetic error on `None`.
- `find_variable_start_frequency` (`bank.py:831–834`) uses the result in `while l > max_length`, which raises a `TypeError` comparing `None` to a number.
- `followup_event_significance` (`matchedfilter.py:1811, 1835`) puts it into `int(lookback + 2.0*trim_pad + length_in_time)`, same class of delayed failure.

The "one bad row stops a whole column" behaviour comes from `numpy.vectorize` at line 561. `vectorize` has no per-element error handling: it evaluates the Python function row by row and the first exception propagates out of the whole call. I verified this directly — an array of three approximants where only the middle one is unknown raises `RuntimeError` and returns nothing, rather than yielding two good durations and one failure. So in `bank_conversions.get_bank_property`, a single template row with an untranslatable approximant destroys the duration column for every template in the bank; and in `events/cuts.py:439`, which calls `get_bank_property`, that same single row takes out the entire template cut for the analysis.

Two related `vectorize` sharp edges in the same line: `otypes` is not set, so an empty template-id selection raises `ValueError: cannot call 'vectorize' on size 0 inputs unless 'otypes' is set` (confirmed experimentally), and the output dtype is inferred from the first element only. Separately, `bank_conversions.py:125`'s fallback `prem_dur = np.zeros_like(template_ids)` inherits the *integer* dtype of the id array (confirmed: `int64`), so the `values -= prem_dur` at line 131 mixes an integer zero array into a float duration — harmless while it is zero, but the wrong dtype for the slot.

### 4. Why configuration turns away names that are perfectly computable

`conversion_options` in `bank_conversions.py:35–39` is a flat hard-coded list of strings. It is the gate for `--template-cuts` (`events/cuts.py:53`, `template_param_choices = bank_conv.conversion_options + template_fit_param_choices`, enforced in `convert_inputstr` at lines 104–107 with `NotImplementedError`), and for `pycbc_plot_bank_corner` (lines 179–182, `KeyError`). But `get_bank_property`'s actual duration branch is `elif parameter.endswith('duration')` (line 87) — a suffix test that accepts far more than the list advertises. Anything ending in `duration` that is not literally `'duration'`, `'template_duration'` or `'premerger_duration'` is computable by the function body and yet is rejected at the door by the whitelist. The gate and the implementation disagree about what the vocabulary is, and the gate is the narrower of the two.

### 5. Why extra-mode figures come out longer, and the symbols mechanism behind it

`get_hm_length_in_time` (`waveform.py:1057–1068`) plus `parse_mode_array` (`waveform.py:395–419`).

`parse_mode_array` normalises the `mode_array` symbol into a list of `(l, m)` integer tuples: a space-separated string is split, floats/ints are stringified via `str(int(ma))`, and each token is unpacked with `l, m = ma`. That unpacking is a two-character destructure, so it only works for single-digit `l` and `m`; an `l = 10` mode string would raise `ValueError: too many values to unpack`. It is invoked both from `props` (line 434, so every waveform call is normalised) and again at the top of `get_hm_length_in_time` (line 1058).

`get_hm_length_in_time` then takes `maxm = max(m for _, m in kwargs['mode_array'])` when modes are given, else `maxm_default` — 4 for the IMRPhenom HM family via `imrphenomhm_length_in_time`, 5 for `SEOBNRv4HM_ROM` via `seobnrv4hm_length_in_time` (lines 1043–1055). It then **rewrites the starting frequency**: `kwargs['f_lower'] = flow * 2./maxm` (line 1067), and asks `get_imr_length` for the duration of a *dominant-mode, aligned-spin* approximant (`IMRPhenomD` standing in for `IMRPhenomHM`/`IMRPhenomPv3HM`/`IMRPhenomXHM`/`IMRPhenomXPHM`; `SEOBNRv4` standing in for `SEOBNRv4HM_ROM`) at that lowered frequency.

The physics is sound: the m-th harmonic reaches the band's lower edge when the orbital frequency is `2/m` of the value at which the (2,2) mode does, so a waveform containing an m=4 or m=5 harmonic genuinely starts earlier and is genuinely longer. For `maxm = 4` the (2,2) duration is evaluated from `f_lower/2`; for `maxm = 5` from `0.4 * f_lower`. That is why extra-mode figures are longer, and why they are longer by a *family-dependent* amount rather than a uniform one — the default `maxm` differs between the two adapters, so the same nominal `f_lower` produces different effective start frequencies for IMRPhenom vs SEOB. On top of that, the 10% pad from line 559 still applies, so an HM duration is `1.1 ×` a (2,2) duration evaluated at a shifted frequency — two separate inflations composed. Note also that the branch is chosen by `maxm` alone: a `mode_array` of `[(2,2)]` gives `maxm = 2`, `f_lower * 2/2 = f_lower`, and the HM path collapses to the plain path, which is the correct degenerate behaviour.

### Where a change would go (not made)

The 10% pad on `pnutils.py:559` is the single line responsible for symptom 1. If the intent is that `get_imr_duration` report a physical duration, the pad belongs in the buffer-sizing callers (`bank.py:599`, `matchedfilter.py:1835`) rather than in the shared primitive; if the intent is that it stay, it needs a comment and the reporting callers need to divide it back out. Symptom 2 would be addressed by giving `_get_imr_duration` the same alias table `_filter_time_lengths` already encodes (and by decoding bytes approximant columns at the `bank_conversions` boundary). Symptom 3 wants either `otypes=` plus per-row error tolerance on the `vectorize` call, or an explicit loop with a documented failure value. Symptom 4 wants `conversion_options` and the `endswith('duration')` branch reconciled. I have deliberately not applied any of these.

### What I could not settle

`lalsimulation`, `lal` and `h5py` are not installed in this environment, so I could not execute `_get_imr_duration` and measure the 1.1 factor against a live library call, nor run a bank through `get_bank_property`. My numpy experiments (bytes-vs-str comparison, `vectorize` first-exception propagation, size-0 `ValueError`, `zeros_like` dtype) were reproduced standalone and are solid. A working lalsuite install would let me confirm the exact ratio numerically and check whether any lalsimulation entry point already includes its own internal margin, which would make the 1.1 a double pad.