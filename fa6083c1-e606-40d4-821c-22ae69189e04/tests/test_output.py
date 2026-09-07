"""Deterministic checks for instance fa6083c1-e606-40d4-821c-22ae69189e04.

apache/iotdb @ 8e5e8502d62f3a8310275a242eb39f42f82877ae
Family: dependency_search.
Gold: db/utils/TabletDecoder.java :: decodeValues.

Two graders consume this file and score differently: the teresa path weights each node by
test_weights.json, the Harbor export path records a flat passed/total and ignores the weights.
A guessable node is worth as much as a hard one on the export path, so the pass COUNT must
discriminate too.

Every node grades a RELATION, never co-occurrence. `re.search(A, ans) and re.search(B, ans)`
only proves both tokens appear somewhere; it does not prove they stand in the claimed relation.
The trap here is the public twin decodeTime in the same class: it does almost the same job and
shares five of six callees, differing only by recordMemoryUsage and by calling
decodeColumnForTimeStamp in place of decodeColumn. Attribution is therefore gated at file, class
AND function, because an answer enumerating the twin's set is wrong while sharing most tokens.
"""

import json
import os
import re

INSTANCE_ID = "fa6083c1-e606-40d4-821c-22ae69189e04"


def _in_bundle(path):
    """True when `path` sits in this bundle directory.

    The grader's only answer source is the rollout row on HG_OUTPUT_JSONL; truth.md is never
    handed to pytest. Refusing any in-bundle path means the suite cannot be made to pass by
    feeding it its own ground truth, which is the one way to get a false green here.
    """
    try:
        return os.path.dirname(os.path.abspath(path)) == os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return False


def _rollout_rows():
    """Every JSONL row that could carry this instance's result.

    A row with no instance field is accepted: single-instance runs emit one unlabelled row.
    """
    jf = os.environ.get("HG_OUTPUT_JSONL", "")
    if not (jf and os.path.exists(jf)):
        return []
    rows = []
    for line in open(jf):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        iid = rec.get("instance_id") or rec.get("instance") or rec.get("id")
        if iid in (None, INSTANCE_ID):
            rows.append(rec)
    return rows


def _unwrap(val):
    """An answer or patch arrives as a bare string, or nested one level under a text-ish key."""
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ("text", "content", "answer", "value", "message"):
            v = val.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def _get_answer() -> str:
    """HG_ANSWER_FILE -> HG_ANSWER -> rollout -> /logs. Never skips; "" fails loudly."""
    af = os.environ.get("HG_ANSWER_FILE", "")
    if af and os.path.exists(af) and not _in_bundle(af):
        return open(af).read()
    inline = os.environ.get("HG_ANSWER", "")
    if inline.strip():
        return inline
    for rec in _rollout_rows():
        tr = rec.get("test_result") or {}
        if isinstance(tr, dict):
            for k in ("answer", "model_answer", "final_answer", "response", "output"):
                got = _unwrap(tr.get(k))
                if got.strip():
                    return got
        for k in ("model_answer", "answer", "final_answer", "response", "output"):
            got = _unwrap(rec.get(k))
            if got.strip():
                return got
    # Filesystem fallback. /logs/agent/answer.md FIRST: that is where the bundle's own
    # solution/solve.sh writes, and where Harbor's agent phase deposits an answer when the
    # run carries no rollout row. test.sh states the same contract ("the bundle's
    # /logs/agent/answer.md fallback must stay reachable") -- an oracle or no-op agent never
    # writes output.jsonl, so this link is the only one it can reach. The per-instance paths
    # stay as additional candidates for harnesses that namespace /logs by instance.
    # _in_bundle still gates every path, so the suite cannot be passed its own ground truth.
    for local in ("/logs/agent/answer.md", "/logs/agent/answer.txt",
                  f"/logs/{INSTANCE_ID}/answer.md", f"/logs/{INSTANCE_ID}/answer.txt"):
        if os.path.exists(local) and not _in_bundle(local):
            return open(local).read()
    return ""


def _get_patch() -> str:
    """Same chain for the diff. Reading the rollout is what makes the read-only gate real:
    on a harness that carries the patch only in the JSONL, a resolver that stops at
    HG_PATCH_FILE reports a file-editing agent as read-only and leaves the penalty dormant.
    """
    pf = os.environ.get("HG_PATCH_FILE", "")
    if pf and os.path.exists(pf):
        return open(pf).read()
    inline = os.environ.get("HG_PATCH", "")
    if inline.strip():
        return inline
    for rec in _rollout_rows():
        tr = rec.get("test_result") or {}
        if isinstance(tr, dict):
            for k in ("git_patch", "patch", "model_patch", "diff"):
                got = _unwrap(tr.get(k))
                if got.strip():
                    return got
        for k in ("git_patch", "model_patch", "patch", "diff"):
            got = _unwrap(rec.get(k))
            if got.strip():
                return got
    # Same correction for the diff: /logs/verifier/agent.patch is where Harbor writes the
    # agent's patch, matching the sibling bundles. Without it the read-only gate reads an
    # empty patch on the oracle path and reports any agent as read-only.
    for local in ("/logs/verifier/agent.patch", f"/logs/{INSTANCE_ID}/patch.diff"):
        if os.path.exists(local) and not _in_bundle(local):
            return open(local).read()
    return ""


def _norm(ans):
    """Collapse all whitespace so line wrapping cannot change a verdict."""
    return re.sub(r"\s+", " ", ans)


def _near(ans, a, b, window=300):
    """True only when `b` occurs within `window` chars of some `a` match."""
    ans = _norm(ans)
    for m in re.finditer(a, ans, re.I):
        lo, hi = max(0, m.start() - window), min(len(ans), m.end() + window)
        if re.search(b, ans[lo:hi], re.I):
            return True
    return False


def _ordered(ans, first, second, window=300):
    """True only when `second` follows `first` within `window` chars."""
    ans = _norm(ans)
    for m in re.finditer(first, ans, re.I):
        hi = min(len(ans), m.end() + window)
        if re.search(second, ans[m.end():hi], re.I):
            return True
    return False


NEGATED = r"(is|are|was|were|does|do|can|could|would)\s+(not|never)\b|\bneither\b|\bnor\b|\brather than\b"


def _sentences(ans):
    """Split on sentence enders, and on line breaks and bullet markers.

    Splitting only on `[.!?]\\s+` made a bulleted list - the format these prompts elicit - a single
    sentence, so any per-item claim inside it inherited every other item's context.
    """
    parts = []
    for line in re.split(r"[\r\n]+|(?:^|\s)[-*\u2022]\s+", ans):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            parts.extend(p for p in re.split(r"(?<=[.!?])\s+", line) if p.strip())
    return parts


CONTRAST_SPLIT = (r";|,\s*(?:not|and|but|while|whereas|which|where|whose|though)\b"
                  r"|\s+(?:whereas|while|though|although)\s+")


def _clauses(ans):
    """Sentences cut at contrast joins, so a verdict cannot reach across a clause boundary.

    "The defect lies in X, not Y" and "X is the culprit; Y is fine" both name Y in a sentence that
    also carries a verdict idiom. Scoping the verdict to the clause it actually governs is what
    separates an attribution to Y from an exoneration of Y.
    """
    out = []
    for s in _sentences(ans):
        out.extend(c.strip() for c in re.split(CONTRAST_SPLIT, s, flags=re.I) if c.strip())
    return out


def _claims(ans, subject):
    """True only when a sentence AFFIRMATIVELY names `subject` as the thing responsible.

    Polarity-aware: a sentence carrying a negation is an exoneration, not an attribution, so
    "neither listener is responsible" no longer reads as blame. Sentence-scoped rather than
    `[^.]`-scoped, so a dotted identifier cannot decide the verdict.
    """
    verdict = (r"is the (deciding|responsible|guilty|culprit)"
               r"|(function|method|routine|one) responsible is"
               r"|responsible (function|method|routine) is"
               r"|(lies|sits|is) (in|inside|within) [A-Z]\w+"
               r"|is (the )?(function|method|routine|place|site) (that|which) (decides|is responsible)"
               r"|is responsible for (the|this|it)"
               r"|is the culprit|is at fault|is where the (decision|cause|defect)"
               r"|is (lost|swallowed|dropped|discarded|suppressed) (in|by|at|on)"
               r"|deciding (function|method|routine) is"
               r"|the (defect|cause|problem) (is|lies) in")
    for s in _clauses(ans):
        if re.search(subject, s, re.I) and re.search(verdict, s, re.I) \
                and not re.search(NEGATED, s, re.I):
            return True
    return False


def _pins(ans, path, func, cls=None, rivals=()):
    """Attribution: the gold must be named at file, class and function, with no rival claimed.

    Used by exactly ONE node per suite - the one whose job is attribution. Mechanism nodes do
    not call this; they grade facts only a reader of the right code can state.
    `rivals` must never contain a symbol another node requires the answer to explain.
    """
    ans_n = _norm(ans)
    basename = path.rsplit("/", 1)[-1]
    # The prompt asks the solver to name the file, so a distinctive basename is enough - requiring
    # the directory too is a hidden requirement. A GENERIC basename is not enough: `tee.go` matched
    # a probe's non-existent `util/pipe/tee.go` and handed it the attribution node.
    distinctive = len(re.sub(r"\\.|\.\w+$", "", basename)) >= 12 or re.search(r"[A-Z]", basename)
    if not (re.search(path, ans_n) or (distinctive and re.search(basename, ans_n))):
        return False
    if not _near(ans, func, r"\b(calls?|decid\w*|determin\w*|responsib\w*|is the|routine|method|override|"
                   r"chooses|picks|where the (outcome|cause|decision|owner))\b", 350):
        return False
    if cls and not _near(ans, cls, func, 400):
        return False
    return not any(_claims(ans, r) for r in rivals)

BLAME = (r"deciding function|the routine (under audit|in question)|calls directly"
         r"|direct call surface|the routine is|under audit")



def _excluded_in_sentence(ans, symbol, owner=None):
    """True when ONE sentence places `symbol` outside the audited routine's direct call surface.

    Replaces a `_near(symbol, excluded-words, 300)` window. The window graded prose length: the
    same correct answer passed at a 290-character gap to the nearest "excluded" and failed at 312,
    so deleting nine words that changed no fact flipped the verdict. Attribution belongs in the
    sentence that makes the claim.
    """
    excl = (r"exclud|\bindirect\b|not a direct|one frame|transitive|belongs to|only (in|the twin)"
            r"|absent from|reached (from|through|via)|by way of|inside (the )?(private )?\buncompress\b"
            r"|is (a )?callee of|sits inside|deeper|beyond|further down")
    # Attributing the symbol to another routine in the same sentence is an exclusion too:
    # "decodeTime ... additionally calls recordMemoryUsage" places it outside the audited set
    # just as plainly as the word "excluded" does.
    ownership = r"\b(calls?|invokes?|reaches|uses|shares|additionally|also|instead of|its own)\b"
    for s in _sentences(ans):
        if not re.search(symbol, s):
            continue
        if re.search(excl, s, re.I) and (owner is None or re.search(owner, s, re.I)):
            return True
        if owner and re.search(owner, s, re.I) and re.search(ownership, s, re.I):
            return True
    return False


def test_gold_routine_pinned():
    """[former R31] decodeValues in TabletDecoder is the routine under audit.

    Sole attribution node. decodeTime is REQUIRED by test_twin_set_differs, so it is not a
    rival; the twin is separated positively by that node instead.
    """
    assert _pins(_get_answer(), r"db/utils/TabletDecoder\.java", r"\bdecodeValues\b",
                 cls=r"TabletDecoder"), \
        "the routine is not pinned to decodeValues in TabletDecoder.java"


def test_value_column_helper_is_gold_specific():
    """[former R32] decodeColumn once per value column - the twin calls the timestamp helper.

    Gold-unique: decodeColumnForTimeStamp and decodeColumn are not interchangeable, so an
    answer about the twin names the wrong helper here.
    """
    a = _get_answer()
    assert _near(a, r"\bdecodeColumn\b(?!ForTimeStamp)",
                 r"per (value )?column|each value column|once per|once for (every|each)"
                 r"|for (every|each) value column|for (every|each) column", 300) \
        and _near(a, r"\buncompress\b", r"private|same class", 250), \
        "decodeColumn per value column and the private uncompress are not both identified"


def test_indirect_metric_excluded():
    """[former R33] recordDecompressLatencyTimer sits INSIDE uncompress - one frame too deep.

    Two bindings, because neither alone survives an over-broad answer. (a) The recorder must be
    placed on the excluded side in the sentence that names it - a bare proximity window let a
    seven-callee answer through, since it mentions `uncompress` a line earlier. (b) The direct
    set must be stated as six; over-inclusion is the failure mode this bundle exists to detect,
    and for a dependency inventory the size of the list is part of the deliverable.
    """
    a = _get_answer()
    assert _excluded_in_sentence(a, r"recordDecompressLatencyTimer", r"\buncompress\b|indirect|one frame"), \
        "the recorder reached inside uncompress is not placed one frame down in the sentence naming it"

def test_metrics_accessor_count_is_gold_specific():
    """[former R34] THREE getInstance invocations - the twin makes four.

    Gold-unique: an answer describing decodeTime cannot state three, because that routine
    additionally records a memory figure. This discriminates without inspecting attribution.
    """
    a = _get_answer()
    assert _near(a, r"getInstance", r"\bthree\b|127.{0,40}129.{0,40}137", 300) and \
        re.search(r"RPCServiceThriftHandlerMetrics", a), \
        "the three invocations of the metrics accessor are not established"


def test_memory_recorder_excluded_from_the_list():
    """[former R35] recordMemoryUsage must be stated as ABSENT from the audited routine's list.

    An answer auditing the twin names recordMemoryUsage as one of ITS callees, so merely
    mentioning it beside decodeTime is not evidence. The exclusion has to be explicit.
    """
    a = _get_answer()
    assert _excluded_in_sentence(a, r"recordMemoryUsage", r"twin|decodeTime|\btimestamp\b|time column"), \
        "recordMemoryUsage is not attributed to the twin routine in the sentence that names it"


def test_external_tsfile_excluded():
    """[former R36] The two externals reached BEYOND the routine must be named as external.

    Retargeted off the bare "tsfile is separate" claim, which rubric R8 grades.
    """
    a = _get_answer()
    named_external = _near(a, r"getDecoderByType|IUnCompressor",
                           r"tsfile|external|further down|deeper|beyond|indirect", 300)
    # An answer that files an org.apache.tsfile symbol under an in-repository module has counted
    # an external as ours, which is the failure this bundle exists to detect. Clause-scoped so the
    # gold's "everything under org.apache.tsfile ... is external" does not trip it.
    placed_in_repo = False
    for c in _clauses(a):
        if not re.search(r"org\.apache\.tsfile|getDecoderByType|IUnCompressor", c):
            continue
        if re.search(r"extern|separate|not (in|part of)|absent|dependency|no source|beyond|indirect", c, re.I):
            continue
        if re.search(r"iotdb-core|datanode|in-?repository|this repository|module that declares"
                     r"|declared (in|by) (this|the) (project|repository)", c, re.I):
            placed_in_repo = True
    assert named_external and not placed_in_repo, \
        "the decoder factory and the decompressor are not named as external and reached beyond"


def test_pair_named_as_external():
    """[former R37] The Pair on the return line is the most natural false inclusion."""
    a = _get_answer()
    assert _near(a, r"\bPair\b", r"tsfile|external|not in this repo|separate", 250), \
        "the Pair constructed on the return line is not identified as external"


def test_timestamp_helper_excluded_from_the_list():
    """[former R38] decodeColumnForTimeStamp belongs to the twin, not to the audited routine."""
    a = _get_answer()
    assert _excluded_in_sentence(a, r"decodeColumnForTimeStamp", r"twin|decodeTime|\btimestamp\b|\btime column\b"), \
        "decodeColumnForTimeStamp is not attributed to the twin in the sentence that names it"


def test_encoding_slot_convention():
    """[former R39] Slot 0 belongs to the time column; value column i lives at i + 1."""
    a = _get_answer()
    assert _near(a, r"columnEncodings|encoding list", r"get\(0\)|slot 0|first (position|slot)", 300), \
        "the reserved slot-0 convention is absent"


def test_jdk_calls_excluded():
    """[former R40] nanoTime and the ByteBuffer operations are JDK, not repository code."""
    a = _get_answer()
    assert _near(a, r"nanoTime|ByteBuffer|remaining\(\)", r"JDK|standard library|java\.|stdlib", 250) \
       , \
        "the JDK calls are not excluded with a reason"


def test_metrics_declarations_cited():
    """[former R27] The declaring file must be read, not inferred from the import line.

    Without this the whole answer is obtainable from TabletDecoder.java alone: an answer sourced
    only from the gold file, deriving the metrics class from its own import, scored full marks.
    A dependency inventory records the DECLARING file, so the declaration sites are the deliverable.
    """
    a = _get_answer()
    declaring_file = _near(a, r"RPCServiceThriftHandlerMetrics",
                           r"RPCServiceThriftHandlerMetrics\.java|\.java\b|declared in|declaring file", 320)
    module = _near(a, r"RPCServiceThriftHandlerMetrics", r"iotdb-core[/ -]?datanode|datanode module", 420)
    together = _near(a, r"recordUnCompressionSizeTimer|recordCompressionSizeTimer|recordDecodeLatencyTimer",
                     r"same (file|class)|all three .{0,30}(declared|in)|RPCServiceThriftHandlerMetrics\.java"
                     r"|\b51\b|\b55\b|\b59\b|\b173\b", 400)
    assert declaring_file and module and together, \
        "the metrics recorders are not paired with their declaring file and module"


def test_indirect_recorder_counted_as_direct():
    """[former R30] NEGATIVE. Penalise listing the indirect recorder among the direct callees.

    `recordDecompressLatencyTimer` is invoked at TabletDecoder.java:102, inside the private
    `uncompress` - one frame below the audited routine. The prompt states that "anything the
    routine reaches only by way of something else it calls is an exclusion as well" and that an
    unjustifiable entry "counts against us more heavily than a late one", so over-inclusion is the
    failure mode this bundle exists to detect. This used to be caught only by requiring the literal
    word "six" near "call", which is a bare count as the gradable point and duplicated rubric R1.
    """
    a = _get_answer()
    direct = (r"\bcalls?\b|\bit calls\b|\bdirect\b|in-?repository|declared (in|at)"
              r"|all (three|four)|reach\w*|uses?|invok\w*|through it|\bfour\b|\bseven\b")
    # Listing it beside the three genuinely-direct recorders is itself the over-inclusion, whatever
    # verb the sentence uses: a fresh seven-callee answer said "reaches four recorders through it"
    # and matched none of the earlier vocabulary.
    siblings = r"recordUnCompressionSizeTimer|recordCompressionSizeTimer|recordDecodeLatencyTimer"
    exonerating = (r"exclud|\bindirect\b|one frame|transitive|by way of|reached (from|through|via)"
                   r"|deeper|further down|\buncompress\b")
    for s in _sentences(a):
        if not re.search(r"recordDecompressLatencyTimer", s):
            continue
        # A sentence that names `uncompress` is attributing the recorder to the frame below,
        # which is the correct placement - gold does exactly this at TabletDecoder.java:101-102.
        if re.search(exonerating, s, re.I):
            continue
        if re.search(direct, s, re.I) or re.search(siblings, s):
            return
    assert False, "No over-inclusion found (penalty requires the indirect recorder to be listed as direct)"


def test_read_only_respected():
    assert not _get_patch().strip(), "Agent modified files (patch is non-empty)"


def test_modified_code_penalty():
    assert _get_patch().strip(), "No file modification found (penalty requires a non-empty patch)"
