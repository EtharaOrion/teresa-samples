from __future__ import annotations

import os
import re
from pathlib import Path

_ANSWER_ENV = "HG_ANSWER_FILE"
_PATCH_ENV = "HG_PATCH_FILE"
_ANSWER_FALLBACKS = ("/logs/agent/answer.md", "answer.md")
_PATCH_FALLBACKS = ("/logs/verifier/agent.patch", "patch.diff")
_JSONL_ENV = "HG_OUTPUT_JSONL"


def _from_output_jsonl() -> tuple[str, str] | None:
    import json

    path = os.environ.get(_JSONL_ENV)
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        record = json.loads(fh.readline())
    result = record.get("test_result") or {}
    answer = result.get("answer")
    if isinstance(answer, dict):
        answer = answer.get("text") or next(
            (v for v in answer.values() if isinstance(v, str)), ""
        )
    return str(answer or ""), str(result.get("git_patch") or "")


def _read_first(env_var: str, fallbacks: tuple[str, ...]) -> str:
    here = Path(__file__).resolve().parent
    candidates: list[str] = []
    env_val = os.environ.get(env_var)
    if env_val:
        candidates.append(env_val)
    for fb in fallbacks:
        p = Path(fb)
        candidates.append(str(p if p.is_absolute() else here / p))
    for c in candidates:
        try:
            text = Path(c).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if text.strip():
            return text
    return ""


def _answer() -> str:
    src = _from_output_jsonl()
    if src is not None:
        return src[0]
    return _read_first(_ANSWER_ENV, _ANSWER_FALLBACKS)


def _patch() -> str:
    src = _from_output_jsonl()
    if src is not None:
        return src[1]
    return _read_first(_PATCH_ENV, _PATCH_FALLBACKS)



_WINDOW = 300
_WIDE_WINDOW = 460

_GOLD = r"\b_get_imr_duration\b"
_GOLD_EITHER = r"\b_?get_imr_duration\b"

_FACTOR = r"\b1\.1\b|\b10\s?%|\bten\s+per\s?cent\b|\b10\s+per\s?cent\b"
_PADDING_WORD = (
    r"(?i)\b(?:multipl\w*|pads?|padded|padding|inflat\w*|factor|margin|fudge"
    r"|safety|longer)\b"
)

_BANK = r"\bget_bank_property\b"
_APPROXIMANT = r"(?i)\bapproximants?\b"
_FORWARDS = (
    r"(?i)\b(?:forwards?|forwarded|forwarding|verbatim|straight|passes|passed"
    r"|passing|hands|handed|raw|per-row|column)\b"
)
_FEEDS = (
    r"(?i)\b(?:approximant=|passes|passed|passing|hands|handed|feeds?|supplies"
    r"|supplied|argument|calls?|called|calling|accepts?|value|translat\w*"
    r"|selects?|picks?)\b"
)
_DURATION_MAP = r"\b_APPROXIMANT_DURATION_MAP\b"
_REFUSES = (
    r"(?i)\b(?:rais\w*|refus\w*|reject\w*|error|fails?|failed|failing|blows?|blew"
    r"|invalid|turn(?:s|ed|ing)?\s+away|turn(?:s|ed|ing)?\s+down|blocks?|blocked"
    r"|blocking|stops?|stopped|denies|denied|throws?|threw|thrown)\b"
)
_PEAK_BLOCKED = r"\bSEOBNRv5Peak\b|\bIMRPhenomDPeak\b|\bSEOBNRv1Peak\b"
_CUTOFF_TABLE = r"\bnamed_frequency_cutoffs\b"

_ROM_SPELLING = r"\bSEOBNRv4_ROM\b"
_BARE_SPELLING = r"\bSEOBNRv4\b"
_ROM5_SPELLING = r"\bSEOBNRv5_ROM\b"
_ADMITS = (
    r"(?i)\b(?:accepts?|accepted|admits?|admitted|allows?|allowed|handles?"
    r"|handled|bare|literal|recognis\w*|recogniz\w*)\b"
)

_LENGTH_STUB = r"\bseobnrv4_length_in_time\b"
_REGISTRY = r"\b_filter_time_lengths\b"

_RAISE = r"(?i)\brais(?:e|es|ed|ing)\b|\bRuntimeError\b"
_LIBRARY = r"(?i)\blalsim\w*|\bLAL\b"
_NO_LIBRARY_CALL = (
    r"(?i)\bnothing\b|\bnone\b"
    r"|\bbefore\s+(?:any|the|it|its|a|calling|reaching|invoking|entering)\b"
    r"|\bnever\s+(?:call\w*|reach\w*|invok\w*|enter\w*|touch\w*)\b"
    r"|\bno\s+(?:call|library|lal|lalsim)\w*"
    r"|\bpurely\s+python\b|\bplain\s+python\b|\bpure\s+python\b"
    r"|\boriginates\s+in\b|\binside\s+pycbc\b|\bwithin\s+pycbc\b"
)

_GET_FREQ = r"\bget_freq\b"
_GETATTR = r"\bgetattr\b"
_RESOLVES = (
    r"(?i)\b(?:resolv\w*|attribute|look\w*[\s-]?up|lookup|looks?\s+up|looked\s+up"
    r"|dynamic\w*|fetch\w*|retriev\w*)\b"
)

_PNUTILS_PATH = r"pycbc/pnutils\.py"
_ABSENT = (
    r"(?i)appears\s+in\s+no\s+line|\bno\s+line\s+of\b|\babsent\b|\bnowhere\b"
    r"|\bnever\s+(?:writes|written|appears|mentions|mentioned|spells|spelled)\b"
    r"|\bdoes\s+not\s+appear\b|\bdoes\s+not\s+occur\b|\bzero\s+(?:hits|occurrences)\b"
    r"|\bno\s+(?:occurrence|hit|mention|instance)"
)

_VECTORIZE = r"(?i)\bnumpy\.vectorize\b|\bvectoriz\w*"
_DASH = r"[\s\u2010-\u2015-]?"
_PER_TEMPLATE = (
    r"(?i)\b(?:one|each|a|single|per)\s+(?:template|row|element)\s+at\s+a\s+time"
    r"|\bper" + _DASH + r"(?:template|row)\b"
    r"|\bonce\s+per\s+(?:template|row)\b"
    r"|\btemplate" + _DASH + r"by" + _DASH + r"template\b"
    r"|\brow" + _DASH + r"by" + _DASH + r"row\b"
    r"|\beach\s+(?:template|row)\b"
)

_ORIGIN = (
    r"(?i)\b(?:root cause|origin\w*|owns?|owned|introduces?|introduced|responsible"
    r"|culprit|to blame|at fault|comes? from|stems? from|causes?|caused|causing"
    r"|produces?|produced|imposes?|imposed|source of|applies|applied|applying"
    r"|unconditionally|decides?|decided|is where|funnels?|emits?|returns?)\b"
)
_SYMPTOM = r"(?i)\b(?:durations?|inflat\w*|padded|padding|longer|fraction)\b"
_EXONERATION = (
    r"(?ix)"
    r"(?:is|are|was|were|remains|stays|behaves|looks|seems|appears|acts)"
    r"\s+(?:\w+\s+){0,2}"
    r"(?:correctly|correct|sound|fine|innocent|blameless|harmless|benign"
    r"|intended|appropriate)\b"
    r"|(?:is|are|was|were)\s+(?:not|never)\s+(?:\w+\s+){0,3}"
    r"(?:cause|culprit|source|origin|reason|problem|responsible|fault|blame"
    r"|defect|bug|issue)\b"
    r"|(?:nothing|not)\s+(?:wrong|amiss|faulty|defective|at\s+fault|to\s+blame)\b"
    r"|\bexonerat\w*|\babsolv\w*|\bacquit\w*|\bvindicat\w*"
    r"|\b(?:innocent|blameless)\b"
)
_DOWNSTREAM = (
    r"(?i)\bdownstream\b|\bsecondary\b|\bcontributor\b|\bcontributing factor\b"
    r"|\bside[- ]effect\b|\bsymptom of\b|\bconsequence of\b|\binherits?\b"
    r"|\b(?:merely|only|just)\s+(?:forwards?|passes|relays|reflects|transmits)\b"
    r"|\bresult of\b|\bderived from\b"
)

_OTHER_SYMBOL = re.compile(
    r"\bget_imr_length\b|\bget_hm_length_in_time\b|\b_filter_time_lengths\b"
    r"|\b[a-z0-9]+_length_in_time\b|\bvectoriz\w*|\bget_bank_property\b"
    r"|\bbackground_bin_from_string\b|\b_APPROXIMANT_DURATION_MAP\b"
    r"|\bget_freq\b|\bget_inspiral_tf\b|\bget_final_freq\b"
    r"|\bnamed_frequency_cutoffs\b|\bfrequency_cutoff_from_name\b"
    r"|\bfindchirp_chirptime\b|\blalsim\w*"
    r"|\bget_imr_duration\b",
    re.IGNORECASE,
)
_ACCUSATION = re.compile(
    r"\bculprit\b|\bcaus\w*|\bresponsib\w*|\bblame\w*|\bat fault\b|\borigin\w*"
    r"|\broot\b|\bdefect\w*|\bbug\b|\bguilty\b|\bowns?\b|\bfault\w*",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?][\s\"'\)\]]")
_BLOCK_BREAK = re.compile(
    r"\n[ \t]*\n|\n[ \t]*#{1,6}[ \t]|\n[ \t]*[-*+][ \t]|\n[ \t]*\d+\.[ \t]"
)
_SECTION_BREAK = re.compile(
    r"\n[ \t]*#{1,6}[ \t]|\n[ \t]*[-*+][ \t]|\n[ \t]*\d+\.[ \t]"
)
_RIVAL_OWNER = re.compile(
    r"\bget_imr_length\b|\bget_hm_length_in_time\b|\b\w+_length_in_time\b"
    r"|\b_filter_time_lengths\b|\bfindchirp_chirptime\b",
    re.IGNORECASE,
)


_CONTEXT_EDGE = re.compile(
    r"[.!?][\s\"'\)\]]|\n[ \t]*#{1,6}[ \t]|\n[ \t]*\n|\n[ \t]*[-*+][ \t]"
)


def _sentence_context(text: str, begin: int, end: int, reach: int = 400) -> str:
    left = text[max(0, begin - reach):begin]
    cut = 0
    for edge in _CONTEXT_EDGE.finditer(left):
        cut = edge.end()
    right = text[end:end + reach]
    edge = _CONTEXT_EDGE.search(right)
    stop = edge.end() if edge is not None else len(right)
    return left[cut:] + text[begin:end] + right[:stop]


def _is_inventory(slice_: str, patterns: tuple[str, ...]) -> bool:
    required: list[tuple[int, int]] = []
    for pattern in patterns:
        required.extend((m.start(), m.end()) for m in re.finditer(pattern, slice_))
    strangers = set()
    for other in _OTHER_SYMBOL.finditer(slice_):
        if any(other.start() < end and start < other.end() for start, end in required):
            continue
        strangers.add(other.group(0).lower())
    return len(strangers) > 2


def _claim_span(
    text: str,
    *patterns: str,
    window: int = _WINDOW,
    rivals: bool = False,
    forbid: str | None = None,
) -> str | None:
    hits: list[tuple[int, int, int]] = []
    for index, pattern in enumerate(patterns):
        found = [(m.start(), m.end(), index) for m in re.finditer(pattern, text)]
        if not found:
            return None
        hits.extend(found)
    hits.sort()
    wanted = len(patterns)
    for start_at in range(len(hits)):
        missing = set(range(wanted))
        end = hits[start_at][1]
        for probe in range(start_at, len(hits)):
            missing.discard(hits[probe][2])
            end = max(end, hits[probe][1])
            if missing:
                continue
            begin = hits[start_at][0]
            if end - begin > window:
                break
            candidate = text[begin:end]
            if _SECTION_BREAK.search(candidate):
                break
            if _is_inventory(candidate, patterns):
                break
            if rivals or forbid is not None:
                context = _sentence_context(text, begin, end)
                if rivals and _RIVAL_OWNER.search(context):
                    break
                if forbid is not None and re.search(forbid, context):
                    break
            return candidate
    return None


def _verdict_on_gold(text: str, verdict: str, window: int = 220) -> str | None:
    verdict_re = re.compile(verdict)
    for gold in re.finditer(_GOLD, text):
        ahead = text[gold.end():gold.end() + window]
        block = _BLOCK_BREAK.search(ahead)
        if block is not None:
            ahead = ahead[:block.start()]
        hit = verdict_re.search(ahead)
        if hit is not None:
            between = ahead[:hit.start()]
            if not _OTHER_SYMBOL.search(between) and not _ACCUSATION.search(between):
                return (text[gold.start():gold.end()] + ahead[:hit.end()]).strip()
        behind = text[max(0, gold.start() - window):gold.start()]
        cut = 0
        for block in _BLOCK_BREAK.finditer(behind):
            cut = block.end()
        behind = behind[cut:]
        last = None
        for candidate in verdict_re.finditer(behind):
            last = candidate
        if last is not None:
            between = behind[last.end():]
            if (
                not _OTHER_SYMBOL.search(between)
                and not _ACCUSATION.search(between)
                and not _SENTENCE_END.search(between)
            ):
                return (behind[last.start():] + text[gold.start():gold.end()]).strip()
    return None



_COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', "'''", "<!--")
_STRUCTURAL = ("new file mode", "deleted file mode", "rename from", "rename to",
               "copy from", "copy to")


def _is_comment(text: str) -> bool:
    s = text.strip()
    return not s or s.startswith(_COMMENT_PREFIXES)


def _non_comment_edits(patch: str) -> list[tuple[str | None, str]]:
    offenders: list[tuple[str | None, str]] = []
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith(_STRUCTURAL):
            offenders.append((current, line))
            continue
        if line.startswith("diff --git") or line.startswith("index "):
            continue
        if line.startswith("+++ "):
            raw = line[4:].strip()
            current = None if raw == "/dev/null" else re.sub(r"^b/", "", raw)
            continue
        if line.startswith("--- ") or line.startswith("@@") or line.startswith("\\"):
            continue
        if line.startswith("+"):
            if not _is_comment(line[1:]):
                offenders.append((current, line[1:]))
        elif line.startswith("-"):
            offenders.append((current, line))
    return offenders




def test_identifies_pnutils_file() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    assert re.search(r'pycbc/pnutils\.py', answer), \
        'response does not cite pycbc/pnutils.py'


def test_binds_padding_factor_to_gold_helper() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(
        answer, _GOLD, _FACTOR, _PADDING_WORD,
        window=_WIDE_WINDOW, rivals=True, forbid=_EXONERATION,
    )
    assert span is not None, (
        "response does not put _get_imr_duration, the padding factor and a padding "
        "word inside one claim"
    )


def test_binds_bank_forwarding_to_gold_helper() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(
        answer, _BANK, _APPROXIMANT, _FORWARDS, _REFUSES, _ROM_SPELLING
    )
    assert span is not None, (
        "response does not state that get_bank_property hands the bank's own "
        "SEOBNRv4_ROM spelling on to the gate that then refuses it"
    )


def test_binds_duration_map_to_rom_spelling() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _DURATION_MAP, _ROM5_SPELLING, _FEEDS)
    assert span is not None, (
        "response does not connect _APPROXIMANT_DURATION_MAP to the SEOBNRv5_ROM "
        "spelling it has to supply"
    )


def test_binds_peak_bin_refusal_to_listed_cutoff() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _PEAK_BLOCKED, _CUTOFF_TABLE, _REFUSES)
    assert span is not None, (
        "response does not show a peak frequency bin type turned away while "
        "named_frequency_cutoffs already lists it"
    )


def test_v4_gate_turns_away_rom_spelling() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _ROM_SPELLING, _BARE_SPELLING, _ADMITS, _REFUSES)
    assert span is not None, (
        "response does not set the admitted bare SEOBNRv4 against the refused "
        "SEOBNRv4_ROM in one claim"
    )


def test_registration_key_binds_stub_to_rom_spelling() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _REGISTRY, _ROM_SPELLING, _LENGTH_STUB)
    assert span is not None, (
        "response does not tie the _filter_time_lengths SEOBNRv4_ROM key to "
        "seobnrv4_length_in_time"
    )


def test_raise_precedes_any_library_call() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _RAISE, _LIBRARY, _NO_LIBRARY_CALL)
    assert span is not None, (
        "response does not state that the raise happens before any lalsim routine "
        "is called"
    )


def test_getattr_resolves_the_cutoff_name() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _GET_FREQ, _GETATTR, _RESOLVES)
    assert span is not None, (
        "response does not show get_freq resolving a cutoff name through getattr"
    )


def test_refused_spelling_absent_from_pnutils() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _ROM_SPELLING, _PNUTILS_PATH, _ABSENT)
    assert span is not None, (
        "response does not place SEOBNRv4_ROM outside every line of pycbc/pnutils.py"
    )


def test_alias_evaluates_one_template_at_a_time() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(answer, _VECTORIZE, _APPROXIMANT, _PER_TEMPLATE)
    assert span is not None, (
        "response does not tie the vectorised alias to per-template evaluation of "
        "the approximant column"
    )


def test_gold_helper_held_at_fault() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    assert re.search(_GOLD, answer), 'response does not name _get_imr_duration'
    slip = _verdict_on_gold(answer, _EXONERATION)
    assert slip is None, f'response clears _get_imr_duration: {slip!r}'


def test_gold_helper_is_origin_of_the_inflation() -> None:
    answer = _answer()
    assert answer, "no agent answer available to grade"
    span = _claim_span(
        answer, _GOLD, _ORIGIN, _SYMPTOM,
        window=_WIDE_WINDOW, rivals=True, forbid=_EXONERATION,
    )
    assert span is not None, (
        "response does not make _get_imr_duration the origin of the durations it "
        "inflates"
    )
    demoted = _verdict_on_gold(answer, _DOWNSTREAM)
    assert demoted is None, (
        f'response casts _get_imr_duration as a downstream or secondary effect: {demoted!r}'
    )


def test_read_only_respected() -> None:
    offenders = _non_comment_edits(_patch())
    assert not offenders, f"agent modified code (task is read-only): {offenders[:10]}"


def test_modified_code_penalty() -> None:
    offenders = _non_comment_edits(_patch())
    assert offenders, (
        "no forbidden code modification detected -- penalty criterion not met "
        "(clean read-only run, the good case)"
    )


def _sentences(text):
    return re.split(r"(?<=[.\n;:])\s+", text)


def _any(patterns, s):
    return any(re.search(p, s, re.IGNORECASE) for p in patterns)


def _trap_fires(text, trigger, require, exon):
    # Exoneration is checked across a 3-sentence window (previous + current +
    # next) rather than only the single sentence matching trigger/require, so
    # a correct answer that states its denial and its justification as
    # separate sentences isn't penalized for the sentence break.
    sents = _sentences(text)
    for i, s in enumerate(sents):
        if _any(trigger, s) and _any(require, s):
            window = " ".join(sents[max(0, i - 1):i + 2])
            if not _any(exon, window):
                return True
    return False


def test_blames_hm_length_for_inflation_penalty():
    assert _trap_fires(_answer(), ('get_hm_length_in_time', ), ('get_hm_length_in_time.{0,90}(inflat\\w*|proportional|padding factor|multiplies|the cause|responsible|root cause|source of)', '(inflat\\w*|proportional|padding factor|multiplies|the cause|responsible|root cause|source of).{0,90}get_hm_length_in_time', ), ('\\bnot\\b', 'genuine second', 'second mechanism', 'dodges', 'part of the explanation', 'survives the ROM', 'filtering route', ))


def test_blames_numpy_vectorize_penalty():
    assert _trap_fires(_answer(), ('numpy\\.vectorize', 'np\\.vectorize', ), ('(numpy|np)\\.vectorize.{0,90}(alter\\w*|changes?|source of|the cause|responsible|inflat\\w*|modif\\w*)', '(alter\\w*|changes?|source of|the cause|responsible|inflat\\w*|modif\\w*).{0,90}(numpy|np)\\.vectorize', ), ('public face', 'assignment', 'git grep', '\\bwrapper\\b', 'exposes', 'line 561', 'identifier that owns', '\\bnot\\b', ))


def test_blames_get_freq_for_refusal_penalty():
    assert _trap_fires(_answer(), ('get_freq', ), ('get_freq.{0,90}(turns? away|refus\\w*|reject\\w*|raises?|denies|blocks?)', '(turns? away|refus\\w*|reject\\w*|raises?|denies|blocks?).{0,90}get_freq', ), ('frequency', 'resolves the attribute', 'pnutils\\.py:380', 'getattr', 'different reason', 'same defect', '\\bnot\\b', ))
