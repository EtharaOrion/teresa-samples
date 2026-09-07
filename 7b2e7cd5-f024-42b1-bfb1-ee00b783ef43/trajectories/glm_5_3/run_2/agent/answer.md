I've been asked to continue and finish. Let me compose a final, clean, self-contained answer in prose covering everything, then call finish. I should stop emitting bash calls and just write the deliverable now. Let me write the complete answer carefully, based on verified line numbers:

- pycbc/pnutils.py:527-559 `_get_imr_duration`, vectorized at 561.
- Branches: 531 SEOBNRv2, 535 IMRPhenomXAS, 538 IMRPhenomD, 541 SEOBNRv4, 545 SEOBNRv5_ROM, 548 SPAtmplt/TaylorF2, 555 else raise, 559 *1.1.
- 'SEOBNRv5' used at pnutils.py:449 and :604.
- Callers: bank_conversions.py:111, 119; triggers.py:134; coinc.py:117.
- coinc.py:40-44 _APPROXIMANT_DURATION_MAP with three keys; line 107 frequency branch SEOBNRv2Peak/SEOBNRv4Peak; line 127 ValueError.
- waveform.py:1057-1068 get_hm_length_in_time; 1043-1048 imrphenomhm (maxm_default 4), 1050-1055 seobnrv4hm (5).
- waveform.py:1387-1394 get_waveform_filter_length_in_time returns None for unknown.
- bank.py:599-601 raises RuntimeError('Template waveform %s not recognized!').
- bank.py:821-837 find_variable_start_frequency loop.
- premerger: bank_conversions values = fullband_dur - prem_dur (lines 128-133).
- bank_conversions.py:132 kwargs with approximant column.

Now write final message and call finish.
All investigation is complete; nothing in the repository was created, edited, or deleted. The full answer follows, then I will finish.

## The file and the one function

**`pycbc/pnutils.py`, function `_get_imr_duration` (lines 527–559)**, published at line 561 as `get_imr_duration = numpy.vectorize(_get_imr_duration)`. Every symptom you described originates inside this one function and its vectorized wrapper; no other code in the tree reimplements this logic.

## Why the reported duration is a constant fraction longer than the library's own number

The final statement of the function is:

```python
return time_length * 1.1
```

Whatever LALSimulation returns is multiplied by 1.10 before any caller sees it. The multiplier is unconditional — it applies identically to every branch (SEOBNRv2, IMRPhenomXAS, IMRPhenomD, SEOBNRv4, SEOBNRv5_ROM, SPAtmplt/TaylorF2), so the reported duration exceeds the underlying library value for the *same* masses, spins and starting frequency by a constant +10 %, across every family and mass range. No additive or per-family correction exists anywhere in the chain.

## The dispatch table (branch → LALSimulation call → values)

| Line | Condition | LALSimulation routine | Arguments |
|---|---|---|---|
| 531–534 | `== "SEOBNRv2"` | `SimIMRSEOBNRv2ChirpTimeSingleSpin` | `chi = SimIMRPhenomBComputeChi(m1,m2,s1z,s2z)`; masses × `lal.MSUN_SI`; `f_low` |
| 535–537 | `== 'IMRPhenomXAS'` | `SimIMRPhenomXASDuration` | masses × `MSUN_SI`, spins, `f_low` |
| 538–540 | `== "IMRPhenomD"` | `SimIMRPhenomDChirpTime` | masses × `MSUN_SI`, spins, `f_low` |
| 541–544 | `== "SEOBNRv4"` | `SimIMRSEOBNRv4ROMTimeOfFrequency` | masses × `MSUN_SI`, spins, `f_low` |
| 545–547 | `== 'SEOBNRv5_ROM'` | `SimIMRSEOBNRv5ROMTimeOfFrequency` | masses × `MSUN_SI`, spins, `f_low` |
| 548–554 | `== 'SPAtmplt'` or `== 'TaylorF2'` | `SimInspiralTaylorF2ReducedSpinChirpTime` | `chi` from `SimInspiralTaylorF2ReducedSpinComputeChi`, amplitude order `-1` |
| 555–556 | else | — | `raise RuntimeError("I can't calculate a duration for %s")` |
| 559 | all | — | `time_length * 1.1` |

## Spelling: what is refused and why one caller survives refusal

The dispatch is **exact string equality**, so near-miss spellings are refused. The canonical trap is `"SEOBNRv5"` versus `"SEOBNRv5_ROM"`: the branch at line 545 accepts only `_ROM`, yet the *same repository* legitimately uses bare `'SEOBNRv5'` at `pnutils.py:449` (`get_final_freq`) and at `pnutils.py:604` (the `tof_func_map` inside `get_inspiral_tf`). A name that works for final-frequency and time–frequency lookups is therefore rejected here. The same rigidity catches `SEOBNRv4_ROM` vs `SEOBNRv4`, `IMRPhenomD_NRTidal` vs `IMRPhenomD`, and `SpinTaylorF2` (which has a `_filter_time_lengths` entry but no `_get_imr_duration` branch).

**Why one caller survives refusal:** the waveform-layer front end `get_waveform_filter_length_in_time` (`pycbc/waveform/waveform.py:1387–1394`) is a *silent pass-through* — for a name absent from `_filter_time_lengths` it returns `None` instead of raising. The one place that handles that explicitly is `pycbc/waveform/bank.py:599–601`, which catches the `None` and raises its own clearly-labelled `RuntimeError('Template waveform %s not recognized!' % approximant)`. So an unrecognized name produces a labelled error in the filter-bank path and a raw `RuntimeError` from pnutils in the duration path — two different failure surfaces for one cause.

A second survivor: `get_bank_property` (`pycbc/tmpltbank/bank_conversions.py:104–107`) only passes `approximant=` when the bank has an `approximant` column. A bank lacking that column silently falls back to the function's default, **`"SEOBNRv4"`**, and never hits the refusal at all — while identical masses under a rejected name die in the same script.

## Why one bad row stops a whole column

`numpy.vectorize` has **no per-element error handling** — no masking, no skipping. All four call sites pass whole arrays at once: `bank_conversions.py:111` and `:119`, `triggers.py:134`, `coinc.py:117`. If a single element's approximant string falls into the `else` at line 555, the `RuntimeError` propagates out of the vectorized call and aborts the entire array operation: every other row's duration — all of them individually computable — is discarded. This is why "one bad row stops a whole column": the vectorized scalar raises, and the array is never assembled.

## Why configuration turns away computable names

`background_bin_from_string` (`pycbc/events/coinc.py:47`) does **not** consult the library or the conversion tables. It gates duration binning on the hardcoded dictionary `_APPROXIMANT_DURATION_MAP` (lines 40–44) with exactly three keys — `'SEOBNRv2duration'`, `'SEOBNRv4duration'`, `'SEOBNRv5duration'` (the last mapping to `'SEOBNRv5_ROM'`) — and its frequency branch (line 107) accepts only `['SEOBNRv2Peak', 'SEOBNRv4Peak']`. Anything else reaches line 127, `raise ValueError('Invalid bin type %s')`. So IMRPhenomD/HM/XAS durations — perfectly computable by `_get_imr_duration` — are turned away purely because the name never made it into the whitelist, even though the generic machinery in `bank_conversions.conversion_options` covers `duration`/`template_duration`/`premerger_duration` and LALSimulation offers many more duration-capable approximants.

## Why extra-mode waveforms report longer durations — the symbols mechanism

`get_hm_length_in_time` (`pycbc/waveform/waveform.py:1057–1068`) is the mechanism:

```python
kwargs = parse_mode_array(kwargs)
if 'mode_array' in kwargs and kwargs['mode_array'] is not None:
    maxm = max(m for _, m in kwargs['mode_array'])
else:
    maxm = maxm_default
try:
    flow = kwargs['f_lower']
except KeyError:
    raise ValueError("must provide a f_lower")
kwargs['f_lower'] = flow * 2./maxm
return get_imr_length(lor_approx, **kwargs)
```

The symbols are `mode_array`, `maxm`, and the `2./maxm` rescaling. A harmonic `(ℓ, m)` radiates at roughly `(m/2)·f₂₂`, so to make the (2,2)-based duration function cover the *lowest* requested harmonic, the wrapper divides the start frequency by `maxm/2` (i.e. multiplies `f_lower` by `2./maxm`) and then calls the ordinary (2,2) duration routine. Because chirp time grows steeply as frequency falls (roughly f^(−8/3)), the lowered `f_lower` yields a systematically longer duration — hence extra-mode waveforms report longer durations. Defaults: `imrphenomhm_length_in_time` uses `maxm_default = 4` (line 1048), `seobnrv4hm_length_in_time` uses `5` (line 1055); `_filter_time_lengths` maps IMRPhenomHM, IMRPhenomPv3HM, IMRPhenomXHM, IMRPhenomXPHM and SEOBNRv4HM_ROM onto these.

## Related behaviour worth noting (premerger arithmetic)

In `get_bank_property`, `template_duration`/`duration` is computed as `fullband_dur` at `f_lower` minus `prem_dur` at `f_final` (lines 109–133), both routed through `get_imr_duration` — so both terms each carry their own 10 % inflation, and the premerger duration for a bank without `f_final` is set to `np.zeros_like(template_ids)` (line 125), not an error.

---

If a fix were ever wanted, it would be confined to `_get_imr_duration` (normalizing aliases such as `SEOBNRv5` → `SEOBNRv5_ROM`, or making the default multiplier explicit/configurable), plus adding names to `_APPROXIMANT_DURATION_MAP` in `coinc.py` — but per your instruction no change has been made.

All questions answered in prose with no repository modifications. Root cause: pycbc/pnutils.py `_get_imr_duration` (lines 527-559), vectorized at line 561 — its unconditional `* 1.1` produces the constant +10 % inflation across all families; its exact-string `if/elif` dispatch refuses names like `SEOBNRv5` (used elsewhere in the same file at lines 449 and 604) and raises `RuntimeError` from inside `numpy.vectorize`, which aborts whole-array calls at bank_conversions.py:111/:119, triggers.py:134 and coinc.py:117 (one bad row kills the column). The silent `None` from `get_waveform_filter_length_in_time` (waveform.py:1387-1394) is why the bank.py path survives with its own labelled error at bank.py:599-601, and the hardcoded three-key whitelist `_APPROXIMANT_DURATION_MAP` in coinc.py:40-44 (plus the two-name frequency branch at line 107) is why computable names are turned away with `ValueError` at line 127. Extra-mode waveforms report longer durations because `get_hm_length_in_time` (waveform.py:1057-1068) rescales `f_lower` by `2./maxm` before calling the (2,2)-based routine, exploiting the f^(-8/3) chirp-time scaling. No files were created, edited, or deleted.