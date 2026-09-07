I think I have enough now. Let me verify the SEOBNRv4HM shim's default maxm and the mode_array parsing edge case, since it only handles two-character strings, plus confirm that get_hm_length_in_time relies on get_imr_length needing a float f_lower. I also want to note that IMRPhenomD uses a maxm default of 4 while SEOBNRv4 uses 5, and that the mode array parser breaks on three-character strings.

One more thing to check is whether phase_order defaults propagate correctly through props() for the SPAtmplt path, since spa_length_in_time requires it -- bank_output_utils passes phase_order=7 explicitly, and bank.py's get_template relies on props() defaults, which seems consistent. I also want to trace how matchedfilter passes tmplt['approximant'] positionally, since if it's bytes rather than a decoded string it would fail the _filter_time_lengths lookup and return None, which supports the idea that only one caller actually survives this refusal path -- worth confirming how the bank table stores the approximant string via h5py and whether it gets decoded before use.
I have everything I need. Here is my analysis.

# The single function behind all four symptoms

Everything you describe converges on **`_get_imr_duration` in `pycbc/pnutils.py` (lines 527–559)**, published under a different name on line 561:

```python
get_imr_duration = numpy.vectorize(_get_imr_duration)
```

## Why it hides from search

The `def` is private (`_get_imr_duration`); the public symbol is created by an assignment, not a `def`. So `grep "def get_imr_duration"` finds nothing, and the public name is a `numpy.vectorize` object rather than a plain function — which also means it has no useful signature introspection and swallows the fact that the underlying call is scalar-at-a-time. The waveform layer adds a second layer of disguise: `pycbc/waveform/waveform.py:1012 get_imr_length` wraps it, and *that* is wrapped again by one-line shims (`seobnrv2_length_in_time`, `seobnrv4_length_in_time`, `seobnrv5_length_in_time`, `imrphenomd_length_in_time`, lines 1023–1041), which are what actually get stored in the `_filter_time_lengths` dict (lines 1085–1111). So a search for the name of the family you care about lands on a dict entry, three hops away from the arithmetic.

## 1. The constant fraction: a hard-coded 1.1

Line 559, after every branch of the dispatch:

```python
    return time_length * 1.1
```

This is a flat 10% pad applied uniformly, independent of family, mass, spin and starting frequency, after the LAL routine has returned. That is exactly the signature you report: a *ratio*, not an offset, identical across every family and mass range. It is not a modelling correction and it is not mentioned at any call site. The other margins in the codebase are additive and therefore cannot produce a fixed ratio: `min_buffer += 0.5` in `pycbc/waveform/bank.py:594`, and `parvals += args.min_duration` in `pycbc/events/triggers.py:137`. Anyone comparing `get_imr_duration(...)` against `lalsimulation.SimIMRPhenomDChirpTime(...)` or `SimIMRSEOBNRv4ROMTimeOfFrequency(...)` for the same inputs will see 1.1× every time.

Note this compounds: `bank.py:599–603` adds `min_buffer` on top of the already-inflated number before rounding up, so the filter buffer carries the 10% too.

## 2. Why a barely-different spelling is refused

The dispatch is a chain of exact `==` comparisons against six string literals (lines 531–554): `"SEOBNRv2"`, `'IMRPhenomXAS'`, `"IMRPhenomD"`, `"SEOBNRv4"`, `'SEOBNRv5_ROM'`, and `'SPAtmplt' or 'TaylorF2'`. There is no normalisation, no prefix matching, no alias table. Line 555–556:

```python
    else:
        raise RuntimeError("I can't calculate a duration for %s" % approximant)
```

So the accepted spellings are asymmetric in a way that is not guessable: `SEOBNRv5_ROM` is accepted but `SEOBNRv5` is not; `SEOBNRv4` is accepted but `SEOBNRv4_ROM` is not. The waveform layer papers over this per-entry — `seobnrv5_length_in_time` passes the literal `"SEOBNRv5_ROM"` and `seobnrv4_length_in_time` passes `"SEOBNRv4"` regardless of what key the caller used — and `pycbc/events/coinc.py:40–44` keeps a *third* private translation table:

```python
_APPROXIMANT_DURATION_MAP = {
    'SEOBNRv2duration': 'SEOBNRv2',
    'SEOBNRv4duration': 'SEOBNRv4',
    'SEOBNRv5duration': 'SEOBNRv5_ROM'
}
```

Three separate spelling-fixup mechanisms for one dispatch is why "the spelling is fine" from the user's point of view and still gets refused: the fixups only cover the paths that were remembered.

## 3. Why one caller survives the refusal and another dies

The two gates behave oppositely.

`get_waveform_filter_length_in_time` (`waveform.py:1387–1395`) is a **silent** gate — unknown approximant returns `None`, never raises. `_get_imr_duration` is a **loud** gate — unknown approximant raises `RuntimeError`. Which one you hit depends on whether the name is registered in `_filter_time_lengths`, not on whether the duration is computable.

Among the `get_waveform_filter_length_in_time` callers:

- `pycbc/waveform/bank.py:599–601` checks the sentinel and converts it into a clear error: `if not buff_size: raise RuntimeError('Template waveform %s not recognized!')`. This caller survives refusal cleanly.
- `pycbc/filter/matchedfilter.py:1811` does **not** check. The `None` travels to line 1835, `bdur = int(lookback + 2.0 * trim_pad + length_in_time)`, and dies there with a `TypeError` that names arithmetic, not approximants. (This call also passes `tmplt['approximant']` straight from the table without the `.decode()` that `TemplateBank.approximant()` at `bank.py:447–455` performs, so a bytes-valued column is itself enough to miss the dict.)
- `pycbc/tmpltbank/bank_output_utils.py:325–335` is the worst case, and it explains "a number fetched fails" silently:

```python
        tmplt_durations = numpy.zeros_like(mass1)
        for i in range(len(mass1)):
            wfrm_length = gwflit(appx, mass1=..., mass2=..., f_lower=..., phase_order=7)
            tmplt_durations[i] = wfrm_length
```

`tmplt_durations` is a float array, so assigning `None` into it does not raise — numpy converts it to `nan`. The bank is written with a silently `nan` `template_duration` column. Note also line 320–323: `appx = approximant.encode()`, so the column is written as **bytes** while the lookup dict is keyed by `str`.

`bank.py:721–726` is the one place that treats a stored duration defensively (`if tmpltdur is None or tmpltdur==0.0`), but it does not test for `nan`, so a `nan` from the bank file is used as-is.

## 4. Why one bad row stops a whole column

`numpy.vectorize` is not a vectorised implementation — it loops and calls the scalar function once per element. In `pycbc/tmpltbank/bank_conversions.py:111–122`:

```python
            fullband_dur = pnutils.get_imr_duration(
                *[bank[k][:][template_ids] for k in imr_args + ['f_lower']],
                **kwargs)
```

where `kwargs` is `{'approximant': bank['approximant'][:][template_ids]}` (line 105) — i.e. the approximant is broadcast per-row too. The first row whose approximant reaches line 555 raises `RuntimeError` out of the entire vectorised call. There is no `try`/`except` in `get_bank_property`, nor in any of its three callers (`pycbc/events/cuts.py:439`, `pycbc/population/live_pastro.py:74`, `bin/plotting/pycbc_plot_bank_corner:185`). So a single mixed-approximant row — one `IMRPhenomXPHM` or `TaylorT4` template in an otherwise fine bank — destroys the whole `template_duration` column, aborts the template cut, and kills the plot. Partial results are impossible by construction: the loop is inside a call that either returns a complete array or throws.

Reinforcing this: since `bank['approximant']` in an HDF5 bank is typically bytes, and the dispatch compares against `str` literals, `b'SEOBNRv4' == 'SEOBNRv4'` is `False` in numpy/Python 3 — so a bank written by `output_bank_to_hdf` can fail on *every* row despite the spelling being correct.

## 5. Why configuration turns away computable names

Two registries exist and neither is derived from the other:

- `_get_imr_duration`'s six-literal chain (`pnutils.py:531–554`) — what can actually be computed.
- `_filter_time_lengths` (`waveform.py:1085–1111`) — what `get_waveform_filter_length_in_time` will admit.

They disagree. `IMRPhenomXAS` has a working branch at `pnutils.py:535–537` (`SimIMRPhenomXASDuration`) and is recognised by `get_final_freq` (`pnutils.py:447`), yet it has **no** `_filter_time_lengths` entry. So `get_waveform_filter_length_in_time('IMRPhenomXAS', ...)` returns `None`, and `bank.get_template` reports "Template waveform IMRPhenomXAS not recognized!" for a name the library can compute perfectly. Conversely `SEOBNRv5` is registered nowhere and only reachable through `coinc.py`'s private map.

The generative machinery only propagates existing entries, never creates missing ones: `td_fd_waveform_transform` (`waveform.py:1136–1158`) copies `_filter_time_lengths[approximant]` to `approximant + '_INTERP'` — it can only extend what is already there. Same for the `PYCBC_WAVEFORM` plugin hook (lines 1126–1132) and `plugin.add_length_estimator` (`pycbc/waveform/plugin.py:58–72`): both write into the dict, neither reconciles it with the `pnutils` chain.

The same split shows up in `coinc.background_bin_from_string`: the duration branch (line 116) accepts three labels via `_APPROXIMANT_DURATION_MAP`, while the frequency branch immediately above (line 107) accepts only two, `['SEOBNRv2Peak', 'SEOBNRv4Peak']`, even though `named_frequency_cutoffs` (`pnutils.py:456–498`) defines `SEOBNRv1Peak`, `SEOBNRv5Peak`, `IMRPhenomDPeak` and the `RD` variants as well. "Few duration labels, fewer frequency ones" is literally two hand-maintained subsets of a larger table.

## 6. Why extra modes lengthen the figure

`get_hm_length_in_time` (`waveform.py:1057–1068`):

```python
def get_hm_length_in_time(lor_approx, maxm_default, **kwargs):
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

The physics is sound and it is the reason for the effect. There is no duration model for higher-mode waveforms, so the code delegates to a **dominant-mode** approximant (`IMRPhenomD` for `imrphenomhm_length_in_time`, `SEOBNRv4` for `seobnrv4hm_length_in_time`, lines 1043–1055). The `m`-th harmonic radiates at `m/2` times the orbital-quadrupole frequency, so it enters the band earlier; to bound the full multi-mode signal you ask the quadrupole model how long it lasts starting from `2/m` times the requested `f_lower`. Hence the scaling `f_lower * 2./maxm`.

The consequences that produce your symptom:

- `maxm` is the **largest** `m` present, so one weak high-`m` mode sets the length for the whole waveform.
- With no `mode_array`, `maxm_default` applies: **4** for the Phenom shims (line 1048) and **5** for `SEOBNRv4HM_ROM` (line 1055). So `IMRPhenomHM`/`XHM`/`XPHM`/`Pv3HM` (lines 1105–1108) start from `0.5 × f_lower` and `SEOBNRv4HM_ROM` (line 1096) from `0.4 × f_lower` — a lengthening that is present even when the caller asked for nothing unusual.
- A pure `(2,2)` `mode_array` gives factor `2/2 = 1.0`, i.e. no lengthening. Adding a `(5,5)` mode gives `0.4` and a correspondingly longer figure. The jump is discrete and driven only by `maxm`.
- `maxm` comes from `parse_mode_array` (`waveform.py:395–421`), which coerces `float`/`int` to a two-character string and unpacks it as `l, m = ma`. That parsing assumes single-digit `l` and `m`, so it cannot express modes above 9 and will raise a `ValueError` about unpacking, not about modes, if given e.g. `'1010'`.
- And of course the resulting number then passes through `get_imr_length` → `_get_imr_duration` → `* 1.1`, so the higher-mode inflation and the 10% pad multiply.

## Summary of where things live

| Symptom | Location |
|---|---|
| Constant 1.1× over the wave library | `pycbc/pnutils.py:559` |
| Barely-different spelling refused | `pycbc/pnutils.py:531–556` (exact `==` chain, `RuntimeError` default) |
| Refusal survived vs. fatal | silent `None` at `waveform.py:1392–1395` vs. raise at `pnutils.py:556`; checked at `bank.py:600`, unchecked at `matchedfilter.py:1811` and `bank_output_utils.py:334` |
| One bad row kills the column | `numpy.vectorize` at `pnutils.py:561` + unguarded call at `bank_conversions.py:111–122` |
| Computable names turned away | `_filter_time_lengths` (`waveform.py:1085–1111`) not reconciled with the `pnutils` chain — `IMRPhenomXAS` is the clearest case |
| Extra modes lengthen durations | `waveform.py:1057–1068`, `f_lower * 2./maxm`, defaults 4 and 5 |

I have made no changes to the repository — this is analysis only. If you want a fix, the minimal set would be: (a) hoist the accepted-approximant spellings into one shared table consulted by both `_get_imr_duration` and `_filter_time_lengths` so the two registries cannot drift; (b) make the 1.1 an explicit, documented, caller-controllable parameter rather than a silent constant; (c) either make `get_waveform_filter_length_in_time` raise instead of returning `None`, or make every caller check the sentinel (`matchedfilter.py:1811` and `bank_output_utils.py:334` are the two that currently do not); and (d) replace the `numpy.vectorize` wrapper with an explicit loop that can report which row failed and continue, so one bad template does not void a whole column.