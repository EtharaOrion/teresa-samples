# Reference answer: which function decides IMR template durations, and why it behaves this way

instance_id: 7b2e7cd5-f024-42b1-bfb1-ee00b783ef43  
repo: gwastro/pycbc  
base_commit: f1e16ea53cff7c7ee60182aa067a5271d7628daa

Everything the reporter is seeing is decided by one private helper: `_get_imr_duration`
in `pycbc/pnutils.py`, lines 527-559 at base commit
`f1e16ea53cff7c7ee60182aa067a5271d7628daa`. It is the only place in the repository
that both (a) decides which approximant spellings are allowed to have a duration at
all, and (b) multiplies the LALSimulation result by a fixed padding factor. No caller
reaches it by name. Its single public face is line 561:

```
get_imr_duration = numpy.vectorize(_get_imr_duration)
```

`git grep _get_imr_duration` at this commit returns exactly two lines in the whole
tree: the `def` at 527 and that `numpy.vectorize` assignment at 561. Every other
module in the repository calls the public `get_imr_duration` name, so the identifier
that owns the behaviour appears nowhere near any symptom.

## Where the behaviour is decided

`pycbc/pnutils.py` lines 527-559, in full:

```
527: def _get_imr_duration(m1, m2, s1z, s2z, f_low, approximant="SEOBNRv4"):
528:     """Wrapper of lalsimulation template duration approximate formula"""
529:     m1, m2, s1z, s2z, f_low = float(m1), float(m2), float(s1z), float(s2z),\
530:                               float(f_low)
531:     if approximant == "SEOBNRv2":
532:         chi = lalsim.SimIMRPhenomBComputeChi(m1, m2, s1z, s2z)
533:         time_length = lalsim.SimIMRSEOBNRv2ChirpTimeSingleSpin(
534:                                 m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, chi, f_low)
535:     elif approximant == 'IMRPhenomXAS':
536:         time_length = lalsim.SimIMRPhenomXASDuration(
537:                            m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, s1z, s2z, f_low)
538:     elif approximant == "IMRPhenomD":
539:         time_length = lalsim.SimIMRPhenomDChirpTime(
540:                            m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, s1z, s2z, f_low)
541:     elif approximant == "SEOBNRv4":
542:         # NB for no clear reason this function has f_low as first argument
543:         time_length = lalsim.SimIMRSEOBNRv4ROMTimeOfFrequency(
544:                            f_low, m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, s1z, s2z)
545:     elif approximant == 'SEOBNRv5_ROM':
546:         time_length = lalsim.SimIMRSEOBNRv5ROMTimeOfFrequency(
547:                            f_low, m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, s1z, s2z)
548:     elif approximant == 'SPAtmplt' or approximant == 'TaylorF2':
549:         chi = lalsim.SimInspiralTaylorF2ReducedSpinComputeChi(
550:             m1, m2, s1z, s2z
551:         )
552:         time_length = lalsim.SimInspiralTaylorF2ReducedSpinChirpTime(
553:             f_low, m1 * lal.MSUN_SI, m2 * lal.MSUN_SI, chi, -1
554:         )
555:     else:
556:         raise RuntimeError("I can't calculate a duration for %s" % approximant)
557:     # FIXME Add an extra factor of 1.1 for 'safety' since the duration
558:     # functions are approximate
559:     return time_length * 1.1
```

Two separate things happen here and they explain every observation.

**The padding.** Line 559 multiplies by `1.1` on the way out. It sits after the
`if`/`elif` chain has closed, so it applies to every branch equally: SEOBNRv2,
IMRPhenomXAS, IMRPhenomD, SEOBNRv4, SEOBNRv5_ROM, SPAtmplt and TaylorF2 all leave
through the same `return`. That is why the inflation is the same proportion for every
waveform family and every mass, and why it never varies with the numbers going in.
Nothing downstream ever removes it.

**The name gate.** Lines 531 to 554 are seven plain Python string comparisons. There
is no normalisation, no aliasing, no prefix handling. The accepted set at this commit
is exactly `SEOBNRv2`, `IMRPhenomXAS`, `IMRPhenomD`, `SEOBNRv4`, `SEOBNRv5_ROM`,
`SPAtmplt` and `TaylorF2`. Anything else falls to line 556 and raises. The set is
internally inconsistent in a way that matters: the v4 branch at 541 accepts the bare
name `SEOBNRv4` and refuses `SEOBNRv4_ROM`, while the v5 branch at 545 does the
mirror image, accepting `SEOBNRv5_ROM` and refusing the bare `SEOBNRv5`. Both branches
call a LAL routine whose own name carries `ROM` (lines 543 and 546), so the spelling
the caller must use bears no relation to the routine that will run.

## The trap

Lines 557-558 are a comment that explains the padding away:

```
557:     # FIXME Add an extra factor of 1.1 for 'safety' since the duration
558:     # functions are approximate
```

It is phrased as a settled engineering decision, with a justification and quotation
marks around "safety". It invites the reader to accept the multiplication as intended
and move on, and it is reinforced from a second file. `pycbc/waveform/waveform.py`
line 1020 says the same thing from the outside:

```
1020:     # 10% margin of error is incorporated in the pnutils function
```

That comment names a module and never a function, so it acknowledges the padding while
pointing at nothing in particular. A reader who accepts either line concludes the
inflation is deliberate, stops tracing, and then attributes the durations being
reported to LALSimulation rather than to PyCBC.

Note for the reviewer: `sanitize: true` strips comments and docstrings from the snapshot the
solver is served, so both quotations above are author-facing provenance for why this task is
hard. No rubric criterion, no deterministic test and no claim in the gold answer below rests
on them.

There is a second trap inside the gold function itself. Its docstring at line 528
reads `"""Wrapper of lalsimulation template duration approximate formula"""`. The
function calls *itself* a wrapper. It is not one: it owns the name gate, the mass unit
conversions and the padding, and there is no deeper PyCBC implementation beneath it.
Anyone who believes the docstring keeps searching downstream for the real routine and
ends up naming a LAL function, or names the public vectorized alias at line 561, which
holds no logic at all.

## Why the private helper is hard to reach

`_get_imr_duration` is underscore-prefixed and is bound to a public name by
`numpy.vectorize` at line 561. The consequences compound:

- No caller anywhere spells `_get_imr_duration`. Searching the tree for it finds the
  definition and the vectorize line, and nothing else.
- Searching for the failing approximant spelling does not lead here either. At this
  commit `SEOBNRv4_ROM` appears in `pycbc/waveform/waveform.py:1095`,
  `bin/pycbc_make_skymap:498` and `bin/plotting/pycbc_plot_qscan:223`, and in no line
  of `pycbc/pnutils.py`. The function that rejects the name never writes the name.
- Lines 529-530 cast every numeric argument with `float()`, so the private helper
  cannot take arrays at all. Callers must go through the vectorized alias, which is
  what puts a layer between the symptom and the code.

The vectorization is also what turns the name gate into a per-row decision. When a
caller hands the alias an array of approximant strings, `numpy.vectorize` broadcasts
and invokes `_get_imr_duration` once per template with that template's own spelling,
so a single row carrying a rejected spelling raises for the whole call.

## Why one route works and the other raises

The same waveform family answers differently depending on which door the caller uses,
and that is the sharpest evidence pointing at the gold.

`pycbc/waveform/waveform.py` lines 1012-1021 and 1028-1031:

```
1012: def get_imr_length(approx, **kwds):
1013:     """Call through to pnutils to obtain IMR waveform durations
1014:     """
1015:     m1 = float(kwds['mass1'])
1016:     m2 = float(kwds['mass2'])
1017:     s1z = float(kwds['spin1z'])
1018:     s2z = float(kwds['spin2z'])
1019:     f_low = float(kwds['f_lower'])
1020:     # 10% margin of error is incorporated in the pnutils function
1021:     return pnutils.get_imr_duration(m1, m2, s1z, s2z, f_low, approximant=approx)
```

```
1028: def seobnrv4_length_in_time(**kwds):
1029:     """Stub for holding the calculation of SEOBNRv4* waveform duration.
1030:     """
1031:     return get_imr_length("SEOBNRv4", **kwds)
```

and the registration at line 1095:

```
1095: _filter_time_lengths["SEOBNRv4_ROM"] = seobnrv4_length_in_time
```

So the filtering machinery looks up `SEOBNRv4_ROM` in `_filter_time_lengths`, gets
`seobnrv4_length_in_time`, and that stub throws the caller's spelling away and
substitutes the literal `"SEOBNRv4"` at line 1031. The gate at `pycbc/pnutils.py:541`
is therefore never shown the `_ROM` spelling on this route, and it succeeds. The
lookup key and the string actually passed to the gold are different strings, which is
exactly why the same approximant works here and raises elsewhere.

The other route hands the caller's spelling straight through.
`pycbc/tmpltbank/bank_conversions.py`, inside `get_bank_property` (defined at line 60),
lines 102-114:

```
102:         # Set up the arguments for get_imr_duration
103:         imr_args = ['mass1', 'mass2', 'spin1z', 'spin2z']
104:         if 'approximant' in bank:
105:             kwargs = {'approximant': bank['approximant'][:][template_ids]}
106:         else:
107:             kwargs = {}
108:
109:         if fullband_req:
110:             # Unpack the appropriate arguments
111:             fullband_dur = pnutils.get_imr_duration(
112:                 *[bank[k][:][template_ids]
113:                   for k in imr_args + ['f_lower']],
114:                 **kwargs)
```

Line 105 forwards the bank file's own `approximant` column verbatim. Real PyCBC banks
carry `SEOBNRv4_ROM` in that column, which is the spelling used at
`bin/pycbc_make_skymap:498` and `examples/inspiral/run.sh:38`. Line 104 is the
switch the reporter is seeing: a bank with no `approximant` column produces an empty
`kwargs`, the gold falls back to its own default `approximant="SEOBNRv4"` from line
527, and the call succeeds; the identical bank with an `approximant` column of
`SEOBNRv4_ROM` reaches line 556 and raises.

`pycbc/events/triggers.py` lines 130-135 is a third caller with the same shape:

```
130:     elif par == 'template_duration':
131:         # default to SEOBNRv4 duration function
132:         if not hasattr(args, 'approximant') or args.approximant is None:
133:             args.approximant = "SEOBNRv4"
134:         parvals = pnutils.get_imr_duration(m1, m2, s1z, s2z, args.f_lower,
135:                                            args.approximant)
```

It substitutes the bare `SEOBNRv4` only when the user supplied nothing. A user who
does supply the ROM spelling gets it forwarded and hits the same raise.

## The config-string whitelist, and how it connects

`pycbc/events/coinc.py` carries a second, independent whitelist that has to agree with
the gold's and does not. Lines 38-44:

```
38: # Mapping used in background_bin_from_string to select approximant for
39: # duration function, if duration-based binning is used.
40: _APPROXIMANT_DURATION_MAP = {
41:     'SEOBNRv2duration': 'SEOBNRv2',
42:     'SEOBNRv4duration': 'SEOBNRv4',
43:     'SEOBNRv5duration': 'SEOBNRv5_ROM'
44: }
```

and inside `background_bin_from_string` (defined at line 47), lines 107-127:

```
107:             elif bin_type in ['SEOBNRv2Peak', 'SEOBNRv4Peak']:
108:                 vals = pycbc.pnutils.get_freq(
109:                     'f' + bin_type,
110:                     data['mass1'],
111:                     data['mass2'],
112:                     data['spin1z'],
113:                     data['spin2z']
114:                 )
115:                 cached_values[bin_type] = vals
116:             elif bin_type in _APPROXIMANT_DURATION_MAP:
117:                 vals = pycbc.pnutils.get_imr_duration(
118:                     data['mass1'],
119:                     data['mass2'],
120:                     data['spin1z'],
121:                     data['spin2z'],
122:                     data['f_lower'],
123:                     approximant=_APPROXIMANT_DURATION_MAP[bin_type]
124:                 )
125:                 cached_values[bin_type] = vals
126:             else:
127:                 raise ValueError('Invalid bin type %s' % bin_type)
```

The dictionary at lines 40-44 exists only to paper over the gold's spelling quirk:
its value for `SEOBNRv5duration` is `SEOBNRv5_ROM` at line 43 precisely because
`pycbc/pnutils.py:545` refuses the bare `SEOBNRv5`. The map is a three-entry
translation table maintained by hand, so a bin type such as `IMRPhenomDduration` or
`TaylorF2duration` falls to the `else` at line 126 and raises at 127, even though
`pycbc/pnutils.py:538` and `:548` compute durations for exactly those two approximants.
The bin parser rejects work the gold is willing to do.

The frequency arm at line 107 has the same defect for a different reason. It hard-codes
two names, then at line 109 prefixes the bin type with `f` and hands it to `get_freq`,
which resolves the attribute dynamically at `pycbc/pnutils.py:380`:

```
380:     lalsim_ffunc = getattr(lalsim, freqfunc)
```

Because that is a `getattr` on the LAL module, any `f`-prefixed cutoff name would
resolve. `named_frequency_cutoffs` in `pycbc/pnutils.py` already lists
`SEOBNRv1Peak` at line 485, `IMRPhenomDPeak` at line 476 and `SEOBNRv5Peak` at line
497, so the only thing blocking those bin types is the two-element literal list at
`pycbc/events/coinc.py:107`.

## The reporter's false belief, refuted by the code

The natural conclusion, and the wrong one, is that the hard failure on the ROM
spelling is LALSimulation refusing to recognise the approximant name. Three lines at
this commit refute it.

First, no library call happens on the failing path. Lines 531-556 are Python string
equality tests; when none matches, control reaches `raise RuntimeError` at line 556
having called nothing from `lalsim`. The error originates in PyCBC.

Second, the very same LAL routines are bound to the bare spellings elsewhere in the
same file. `get_inspiral_tf` builds `tof_func_map` at `pycbc/pnutils.py` lines 600-605:

```
600:         tof_func_map = {
601:             # use HI function for v2 as it has wider freq range validity
602:             'SEOBNRv2': lalsim.SimIMRSEOBNRv2ROMDoubleSpinHITimeOfFrequency,
603:             'SEOBNRv4': lalsim.SimIMRSEOBNRv4ROMTimeOfFrequency,
604:             'SEOBNRv5': lalsim.SimIMRSEOBNRv5ROMTimeOfFrequency
605:         }
```

Line 604 reaches `SimIMRSEOBNRv5ROMTimeOfFrequency`, the identical routine used at
`pycbc/pnutils.py:546`, under the bare key `SEOBNRv5` that the gold refuses.
`get_final_freq` does the same at lines 449-450, special-casing bare `SEOBNRv5`:

```
449:     if approx == 'SEOBNRv5':
450:         return frequency_cutoff_from_name('SEOBNRv5RD', m1, m2, s1z, s2z)
```

Third, the same file already contains the normalisation the gold lacks.
`pycbc/pnutils.py:597` reduces a full approximant name to a family prefix before
lookup:

```
597:         approximant_prefix = approximant[:len('SEOBNRv*')]
```

`_get_imr_duration` never does this, and that omission is the whole difference.

## What exists nearby and is not the cause

`get_imr_length` at `pycbc/waveform/waveform.py:1012` is the most tempting wrong
answer, and it is the wrong answer. It takes the same five arguments as the gold, it
is named for the same job, and its comment at line 1020 openly discusses the ten
percent margin. But lines 1015-1021 perform no arithmetic on the returned value and no
name test: the four `float()` casts at 1015-1019 only unpack keyword arguments, and
line 1021 returns whatever the gold hands back, unmodified. It transmits both effects
and causes neither. Naming it, or naming any of the four stubs beneath it, is naming a
pass-through.

The stubs `seobnrv2_length_in_time` (line 1023), `seobnrv4_length_in_time` (1028),
`seobnrv5_length_in_time` (1033) and `imrphenomd_length_in_time` (1038) are one-line
forwarders that pick a literal string. `seobnrv4_length_in_time` is the reason the
filtering route survives the ROM spelling, so it is part of the explanation, but the
gate it dodges is not its own.

`get_hm_length_in_time` at `pycbc/waveform/waveform.py:1057-1068` is a genuine second
mechanism and it is not the padding:

```
1057: def get_hm_length_in_time(lor_approx, maxm_default, **kwargs):
1058:     kwargs = parse_mode_array(kwargs)
1059:     if 'mode_array' in kwargs and kwargs['mode_array'] is not None:
1060:         maxm = max(m for _, m in kwargs['mode_array'])
1061:     else:
1062:         maxm = maxm_default
1063:     try:
1064:         flow = kwargs['f_lower']
1065:     except KeyError:
1066:         raise ValueError("must provide a f_lower")
1067:     kwargs['f_lower'] = flow * 2./maxm
1068:     return get_imr_length(lor_approx, **kwargs)
```

Line 1067 lowers the starting frequency by a factor `2/maxm` before delegating, with
`maxm` defaulting to 4 for IMRPhenomHM (line 1048) and 5 for SEOBNRv4HM (line 1055).
That is why higher-mode approximants report far longer durations than their
aligned-spin counterparts at identical inputs. It is a different mechanism in a
different file, and confusing it with the gold's flat multiplication is the specific
mistake that makes the padding look family-dependent when it is not.

`get_imr_duration` at `pycbc/pnutils.py:561` is a `numpy.vectorize` alias and holds no
logic; naming it instead of `_get_imr_duration` names the wrapper and not the work.

`test/validation_code/old_coinc.py` lines 91-110 hold a stale copy of the bin parser
with an even narrower whitelist, offering only `SEOBNRv2duration` and
`SEOBNRv4duration`. It is dead validation code, it never mentions the gold, and it
leads away from the answer rather than toward it.

## What the merged PR changed

Pull request #4540, "Rationalize some calls to waveform properties", is closed and
merged into `gwastro/pycbc` master as squash commit
`68e527b36fd89b6496bcdc05444591900dba1e05`, whose single parent is this base commit.
It touched two files and no tests. In `pycbc/pnutils.py` it widened the gold's gate so
that line 541 becomes `elif approximant in ["SEOBNRv4", "SEOBNRv4_ROM"]:` and line 545
becomes `elif approximant in ["SEOBNRv5", "SEOBNRv5_ROM"]:`, and it rewrote the comment
at 542 to drop "for no clear reason". In `pycbc/events/coinc.py` it deleted
`_APPROXIMANT_DURATION_MAP` entirely and replaced both hard-coded whitelists with
suffix tests, so line 107 becomes `elif bin_type.endswith('Peak'):` and line 116
becomes `elif bin_type.endswith('duration'):` with
`approximant=bin_type.replace('duration', '')`. The padding at line 559 and the
`numpy.vectorize` alias at 561 were left untouched, so the ten percent factor is
existing behaviour that survives the fix. None of the merged state exists at this
commit.

## Headline

The responsible file is `pycbc/pnutils.py` and the responsible function is the private
helper `_get_imr_duration`, exposed only as `get_imr_duration` through
`numpy.vectorize` at line 561. Its closing `return time_length * 1.1` at line 559 sits
outside the branch chain and pads every duration the repository produces by the same
factor, whatever the approximant and whatever the masses. Its seven string comparisons
at lines 531-554 are the entire admissible-name policy: `SEOBNRv4` is accepted and
`SEOBNRv4_ROM` is refused at line 541, while line 545 does the reverse for v5, and
anything unmatched raises at line 556 before any LAL routine is called. Whether a
caller survives that gate depends on whether it substitutes a literal, as
`seobnrv4_length_in_time` does at `pycbc/waveform/waveform.py:1031` for the key
registered at line 1095, or forwards the caller's own spelling, as
`get_bank_property` does at `pycbc/tmpltbank/bank_conversions.py:105` and
`pycbc/events/triggers.py:135` does. `_APPROXIMANT_DURATION_MAP` at
`pycbc/events/coinc.py:40-44` is a hand-maintained translation table that exists to
absorb the same quirk, and its three entries are why `background_bin_from_string`
raises at line 127 for duration bin types the gold could compute.

```json <!-- gold -->
{
  "file": "pycbc/pnutils.py",
  "function": "_get_imr_duration",
  "explanation": "_get_imr_duration at pycbc/pnutils.py lines 527-559 is the private helper that owns both behaviours, and it is reached only through the public alias get_imr_duration created by numpy.vectorize at line 561, which is the sole line in the repository that names it. Line 559, return time_length * 1.1, sits after the branch chain has closed, so every approximant and every mass receives the same flat ten percent padding on the LALSimulation value, and no caller removes it. The approximant spelling SEOBNRv4_ROM appears in no line of pycbc/pnutils.py, so the file that refuses that name never writes it, and a search for the failing spelling lands instead on pycbc/waveform/waveform.py line 1095. Lines 531 to 554 are seven plain string equality tests with no normalisation, admitting only SEOBNRv2, IMRPhenomXAS, IMRPhenomD, SEOBNRv4, SEOBNRv5_ROM, SPAtmplt and TaylorF2, and line 541 accepts the bare SEOBNRv4 while refusing SEOBNRv4_ROM whereas line 545 does the mirror image by accepting SEOBNRv5_ROM and refusing the bare SEOBNRv5. An unmatched spelling reaches raise RuntimeError at line 556 having called nothing from lalsim, which refutes the idea that the underlying library is rejecting the name, and pycbc/pnutils.py lines 600-605 prove it further by binding SimIMRSEOBNRv4ROMTimeOfFrequency and SimIMRSEOBNRv5ROMTimeOfFrequency to the bare keys SEOBNRv4 and SEOBNRv5 inside get_inspiral_tf, the same routines the gold calls at lines 543 and 546, while line 597 shows the family prefix normalisation that _get_imr_duration lacks. Which caller survives the gate depends on whether it substitutes a literal or forwards the caller's spelling: seobnrv4_length_in_time at pycbc/waveform/waveform.py line 1031 discards the requested name and passes the literal SEOBNRv4, which is why the key _filter_time_lengths['SEOBNRv4_ROM'] registered at line 1095 works, whereas get_bank_property at pycbc/tmpltbank/bank_conversions.py line 105 forwards the bank file's own approximant column verbatim so a bank carrying SEOBNRv4_ROM raises while the same bank lacking that column falls back to the helper's default approximant SEOBNRv4 from line 527 and succeeds, and pycbc/events/triggers.py lines 132-135 substitutes SEOBNRv4 only when the user supplied nothing. Because numpy.vectorize broadcasts, an approximant column is evaluated one template at a time, and lines 529-530 cast every numeric argument with float() so the private helper cannot accept arrays directly. _APPROXIMANT_DURATION_MAP at pycbc/events/coinc.py lines 40-44 is a hand-maintained three-entry translation table whose SEOBNRv5duration value is SEOBNRv5_ROM purely to absorb the gold's spelling quirk, and background_bin_from_string raises ValueError at line 127 for duration bin types such as IMRPhenomDduration and TaylorF2duration that lines 538 and 548 of the gold could compute, while the literal list at line 107 blocks peak frequency bin types such as SEOBNRv5Peak and IMRPhenomDPeak that named_frequency_cutoffs already lists at pycbc/pnutils.py lines 497 and 476 and that get_freq would resolve through getattr at line 380. get_imr_length at pycbc/waveform/waveform.py lines 1012-1021 is the most tempting wrong answer because it takes the same arguments and its comment discusses the margin, but it performs no arithmetic and applies no name test of its own, forwarding the approximant string it is handed straight to the duration helper and returning what comes back unaltered, and get_hm_length_in_time at lines 1057-1068 is a separate mechanism that lowers f_lower by a factor of two over maxm at line 1067, which is why higher mode approximants report much longer durations and why the padding can be mistaken for something family dependent when it is a single constant multiplication."
}
```
