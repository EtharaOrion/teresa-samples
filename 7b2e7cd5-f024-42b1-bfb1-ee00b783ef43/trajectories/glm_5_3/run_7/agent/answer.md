The user wants me to finish. I need to call the finish tool with a complete message and task_completed. Let me write the full final answer now, covering all the points:

1. The file and one function
2. Why duration is a constant fraction longer
3. Why spelling differences cause failure
4. Why one duration label takes frequency labels
5. Why extra modes report longer durations
6. Why failure is refusing unknown name
7. Why one caller survives refusal
8. Why one bad row stops a whole column
9. Why configuration turns away computable names
10. Why extra-mode figures (the 2/maxm mechanism)

THE FILE AND THE ONE FUNCTION

Everything reported traces to a single function: `_get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4")` in `pycbc/pnutils.py` (line 527), which the rest of the codebase reaches only through its vectorized alias on line 561: `get_imr_duration = numpy.vectorize(_get_imr_duration)`. Its body is a flat if/elif chain of exact string comparisons, one LALSimulation call per accepted spelling, a bare `RuntimeError` in the final else, and one shared return line: `return time_length * 1.1`. Every symptom is a consequence of that shape.

WHY DURATION IS A CONSTANT FRACTION LONGER, EVERYWHERE

The single unconditional `* 1.1` sits on the shared return line, after the whole dispatch chain, so the 10% inflation is applied identically to all six branches and is completely independent of masses, spins and starting frequency. The underlying calls (SimIMRSEOBNRv2ChirpTimeSingleSpin, SimIMRPhenomXASDuration, SimIMRPhenomDChirpTime, SimIMRSEOBNRv4ROMTimeOfFrequency, SimIMRSEOBNRv5ROMTimeOfFrequency, SimInspiralTaylorF2ReducedSpinChirpTime) return the library's own figure; PyCBC then reports 1.1x that figure. A constant multiplicative offset relative to the library value, uniform across every family and mass range, is exactly the signature of this one line - not of any per-family model error. (The callers can also add an arbitrary `--min-duration`, an additive constant, on top.)

WHY SPELLING MATTERS

The dispatch is exact string equality, not prefix or fuzzy matching, so near-miss spellings do not land on their family. `SEOBNRv4_ROM`, `SEOBNRv4P`, `SEOBNRv4HM_ROM` all miss the `"SEOBNRv4"` branch; `IMRPhenomPv2`, `IMRPhenomC`, `IMRPhenomXAS_NRTidalv2` all miss; `TaylorF2_SWAPPER` misses `"TaylorF2"`. Nothing is normalized (no case folding, no trailing-mode stripping, no alias table), so any token outside the six literals falls to the else and raises `RuntimeError("I can't calculate a duration for %s" % approximant)`. That is the whole mechanism: refusing an unknown name is the designed failure mode of this one function.

WHY A DURATION LABEL TAKES FREQUENCY LABELS

In `pycbc/events/triggers.py`, `get_param` recognizes only the exact token `'template_duration'` as a duration. Any other duration-flavored spelling runs off the end of its chain into the next test, `if par in pnutils.named_frequency_cutoffs.keys()`, and is dispatched to `pnutils.frequency_cutoff_from_name` - i.e. it is interpreted as a named frequency cutoff such as SchwarzISCO, IMRPhenomBFinal, IMRPhenomDPeak, SEOBNRv2RD, SEOBNRv4Peak, MECO. Those names are pure functions of mass and spin only; they accept no `f_lower`. So a slightly wrong duration label silently returns a frequency in Hz rather than a length in seconds, with no type error, because both are just floats.

WHY EXTRA MODES REPORT LONGER DURATIONS

`pycbc/waveform/waveform.py` registers `imrphenomhm_length_in_time` (for IMRPhenomHM/Pv3HM/XHM/XPHM) and `seobnrv4hm_length_in_time` (for SEOBNRv4HM_ROM), both delegating to `get_hm_length_in_time(lor_approx, maxm_default, **kwargs)` at line 1057. That helper parses the mode array, takes `maxm` as the largest m present (defaulting to 4 for Phenom, 5 for SEOBNR), and then computes `kwargs['f_lower'] = flow * 2./maxm` before calling `get_imr_length`. A higher mode's gravitational-wave frequency is a multiple of the orbital frequency, so the 22-mode f_low must be divided by 2/maxm to get the *lower* physical starting frequency that the higher mode corresponds to; a lower start frequency means a longer chirp, and the 1.1 fudge is then applied on top. So higher-mode waveforms legitimately report longer durations by construction: the rescaling of f_lower is the mechanism, and the maxm default and mode-array parsing determine how large the effect is.

WHY ONE CALLER SURVIVES THE REFUSAL AND ANOTHER IS STOPPED

The surviving caller is the waveform-generation path in `pycbc/waveform/waveform.py`: `get_waveform_filter_length_in_time` first checks the registry `_filter_time_lengths` (populated at lines 1085-1111) and raises a clear `ValueError("Approximant %s _filter_time_lengths function not available")` for an unregistered name; a registered name is routed through a family wrapper (`seobnrv2_length_in_time`, `seobnrv4_length_in_time`, `imrphenomd_length_in_time`, `imrphenomhm_length_in_time`, `spa_length_in_time`) that translates the alias into one of the six accepted literals, so an unrecognized spelling never reaches `_get_imr_duration` at all, and `pycbc/waveform/plugin.py` (lines 68-72) lets external plugins inject `_filter_time_lengths` entries. The per-row callers have no such shield: `pycbc/events/triggers.py:134`, `pycbc/tmpltbank/bank_conversions.py:111` and `pycbc/events/coinc.py:117` all call `pnutils.get_imr_duration(...)` directly with a user-supplied approximant string, so any unaccepted spelling raises the RuntimeError out of the loop.

WHY ONE BAD ROW STOPS A WHOLE COLUMN

`get_imr_duration` is `numpy.vectorize` over `_get_imr_duration`, and the underlying chain raises on the first unaccepted element. The three per-row call sites pass whole template arrays (mass1, mass2, spin1z, spin2z, f_lower and a single approximant string, or in bank_conversions `bank['approximant'][:][template_ids]` when the bank stores a per-template approximant). One offending row therefore aborts the vectorized evaluation and the exception propagates, discarding the values already computed for the other rows; nothing catches the RuntimeError per-row, so one bad row costs the entire column.

WHY CONFIGURATION TURNS AWAY COMPUTABLE NAMES

`pycbc/tmpltbank/bank_conversions.py` publishes the closed list `conversion_options` (mass1, mass2, spin1z, spin2z, duration, template_duration, mtotal, total_mass, q, invq, eta, chirp_mass, mchirp, chieff/chi_eff/effective_spin, chi_a, premerger_duration). `pycbc/events/cuts.py` builds `template_param_choices = bank_conv.conversion_options + template_fit_param_choices` and its input sanitizer rejects anything not in that list. So although `get_imr_duration` could perfectly well return a duration for many other families, the configuration layer refuses the name before the library is ever consulted - the refusal is a policy choice in the choices list, not a computational impossibility. `get_param` in triggers.py is slightly looser (it also accepts the named cutoffs and a pass-through to `pnutils.get_freq`, i.e. `getattr(lalsim, freqfunc)`), which is precisely why that path mislabels duration-ish inputs as frequencies.

SUMMARY OF THE BRANCHES AND VALUES

Accepted literals and their LAL calls: "SEOBNRv2" -> SimIMRPhenomBComputeChi then SimIMRSEOBNRv2ChirpTimeSingleSpin; "IMRPhenomXAS" -> SimIMRPhenomXASDuration; "IMRPhenomD" -> SimIMRPhenomDChirpTime; "SEOBNRv4" -> SimIMRSEOBNRv4ROMTimeOfFrequency; "SEOBNRv5_ROM" -> SimIMRSEOBNRv5ROMTimeOfFrequency; "SPAtmplt"/"TaylorF2" -> SimInspiralTaylorF2ReducedSpinChirpTime. All are scaled by 1.1 on exit; everything else raises. The alias layer maps SEOBNRv1/v2_ROM_EffectiveSpin/DoubleSpin, EOBNRv2_ROM, SpinTaylorT5 onto the SEOBNRv2 branch; SPAtmplt, TaylorF2, TaylorF2NL, SpinTaylorF2, PreTaylorF2 onto the SPA branch; and routes the HM families through the f_lower * 2/maxm rescaling into the SEOBNRv4 / IMRPhenomD branches.

No files were created, edited or deleted; this is analysis only.