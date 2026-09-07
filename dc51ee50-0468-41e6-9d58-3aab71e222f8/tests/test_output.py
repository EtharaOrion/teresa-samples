import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

ANSWER_KEYS = ("answer", "final_answer", "response", "model_answer", "output", "prediction")
PATCH_KEYS = ("patch", "model_patch", "diff", "git_patch")


def _from_jsonl(keys):
    path = os.environ.get("HG_OUTPUT_JSONL")
    if not path or not os.path.exists(path):
        return None
    found = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            for k in keys:
                v = rec.get(k)
                if isinstance(v, dict):
                    v = v.get("text") or v.get("content")
                if isinstance(v, str) and v.strip():
                    found = v
            tr = rec.get("test_result")
            if isinstance(tr, dict):
                for k in keys:
                    v = tr.get(k)
                    if isinstance(v, dict):
                        v = v.get("text") or v.get("content")
                    if isinstance(v, str) and v.strip():
                        found = v
    return found


def _first_existing(*paths):
    for p in paths:
        if p and os.path.exists(p) and os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    return None


def load_answer():
    text = _from_jsonl(ANSWER_KEYS)
    if text is None:
        text = _first_existing(
            os.environ.get("HG_ANSWER_FILE"),
            "/logs/agent/answer.md",
            "/logs/answer.txt", "/logs/answer.md", "/logs/final_answer.txt",
            os.path.join(HERE, "answer.txt"), os.path.join(HERE, "answer.md"),
        )
    if text is None:
        text = ""
    return text


def load_patch():
    text = _from_jsonl(PATCH_KEYS)
    if text is None:
        text = _first_existing(
            os.environ.get("HG_PATCH_FILE"),
            "/logs/verifier/agent.patch",
            "/logs/patch.diff", "/logs/model_patch.diff", "/logs/patch.txt",
            os.path.join(HERE, "patch.diff"),
        )
    return text or ""


def touched_files(patch):
    if not patch.strip():
        return []
    hits = set()
    for line in patch.splitlines():
        m = re.match(r"^diff --git a/(\S+) b/(\S+)", line)
        if m:
            hits.add(m.group(2))
            continue
        m = re.match(r"^\+\+\+ (?:b/)?(\S+)", line)
        if m and m.group(1) != "/dev/null":
            hits.add(m.group(1))
        m = re.match(r"^--- (?:a/)?(\S+)", line)
        if m and m.group(1) != "/dev/null":
            hits.add(m.group(1))
    if not hits:
        body = [l for l in patch.splitlines()
                if (l.startswith("+") or l.startswith("-"))
                and not l.startswith(("+++", "---"))]
        if body:
            hits.add("<unnamed>")
    return sorted(hits)


def norm(text):
    return " ".join(text.split())


def linked(text, *anchors, span=400):
    for m in re.finditer(anchors[0], text, re.I):
        window = text[max(0, m.start() - span // 2):m.start() + span]
        if all(re.search(a, window, re.I) for a in anchors[1:]):
            return True
    return False


SILENT = (r"\bsilent\w*|\bno error\b|\bnil error\b|\band nil\b|\breturns? nil\b|"
          r"\breturns? success\b|\bsucceeds?\b|\bzero value\b|\bstays? zero\b|\bleft at\b|"
          r"\bnever (errors|fails|complains)|\bnothing (is )?logged\b|\breports success\b|"
          r"\bwithout complaint\b|\bswallow\w*|\bno complaint\b")

FIXES_COLUMNS = (r"\bfixes\b|\bfixed\b|\bdefin\w*|\bdictat\w*|\bsets? the\b|"
                 r"\bcomes? from\b|\bcame from\b|\bsource of\b|\bnames? the\b")

TTL_LAPSE = (r"\bttl\b|\bexpir\w*|\belapsed?\b|\bpassed\b|\bprune\w*|\bevict\w*|\bdrops?\b|"
             r"\bdropped\b|\bdeletes?\b|\bdeleted\b|\bremoves?\b|\bremoved\b|\bolder\b|"
             r"\bages? out\b|\baged out\b")
SURVIVES = (r"\bstale\b|\bstill\b|\bkeeps?\b|\bkept\b|\blast good\b|\bcontinues?\b|"
            r"\bcontinuing\b|\bremains?\b|\bprevious\w*|\bsurviv\w*|\bpersist\w*|"
            r"\blinger\w*|\bholds?\b|\bheld\b|\buntil\b|\bmeanwhile\b|\bin the meantime\b|"
            r"\bfor a while\b|\bgoes on\b|\bcarries on\b|\bgo on being\b|\bprior value\b")


def test_names_the_query_client_file_path():
    assert "tooling/aro-hcp-exporter/pkg/graphquery/public_ips.go" in norm(load_answer()), (
        "the response never gives the full path of the file holding the binding point")


def test_binds_the_request_executor_to_the_decode_it_performs():
    assert linked(norm(load_answer()),
                  r"\bExecuteConvertRequest\b",
                  r"mapstructure\.Decode",
                  r"\bbinds\b|\bbound\b|\bpairs\b|\bmatches\b|\bmarri\w*|\bjoins?\b|"
                  r"\bhinge\b|\bhands\b|\bcalls?\b|\bties\b|\bwires\b|\bcouples\b|"
                  r"\bdecodes? into\b|\bpasses\b"), (
        "the executor is cited with no statement that its decode binds the two ends")


def test_binds_the_destination_struct_to_its_bare_fields():
    assert linked(norm(load_answer()),
                  r"\bPublicIPAddress\b",
                  r"\b102\b",
                  r"\bno (struct )?tags?\b|\buntagged\b|\bbare\b|\btagless\b|"
                  r"\bwithout (a )?tag|\blacks?\b|\bcarry no\b|\bcarries no\b"), (
        "the destination struct is cited with no statement that its fields carry no tags")


def test_binds_the_query_text_to_the_columns_it_fixes():
    assert linked(norm(load_answer()),
                  r"service_tag_usage\.go",
                  r"\b109\b",
                  FIXES_COLUMNS), (
        "the query text is cited with no statement that it fixes the column names")


def test_binds_the_tag_parser_to_its_silent_empty_return():
    assert linked(norm(load_answer()),
                  r"\bparseIPTags\b",
                  r"\b119\b",
                  SILENT), (
        "the parse helper is cited with no statement that its empty branch returns silently")


def test_binds_the_cache_to_the_staleness_it_causes():
    assert linked(norm(load_answer()),
                  r"tooling/metricscache/cache\.go",
                  TTL_LAPSE,
                  SURVIVES), (
        "the cache source is cited with no statement that it keeps serving a stale series")


def test_read_only_respected():
    touched = touched_files(load_patch())
    assert not touched, f"the task is read only but the patch touches {touched}"


def test_modified_code_penalty():
    touched = touched_files(load_patch())
    assert touched, "no file was modified, so the penalty does not apply"


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


def test_penalizes_subscription_scope_as_cause():
    guilty = _trap_fires(load_answer(), ('subscriptionIDs?', 'subscription\\s?(id|scope|filter)'), ('(cause|reason|due to|because|source of|responsible|blame|reason for|why|attribute|attributes?).{0,80}(empt|missing|absent|drop|silent|no metric|no series|hidden|hides|gauge|series)',), ('\\bnot\\b', '\\bmerely\\b', '\\bruns the query\\b', '\\bwrong direction\\b', '\\bpaired\\b', '\\bruled out\\b'))
    assert guilty


def test_penalizes_names_collector_source_as_binding_hinge():
    guilty = _trap_fires(load_answer(), ('service_tag_usage\\.go',), ('(hinge|binds?|binding|resolved|the place where|is where|coupling|couples|marries|marri\\w*|joins?|ties|wires)',), ('\\bproduc\\w*', '\\bconsum\\w*', '\\bnot\\b', 'ExecuteConvertRequest', 'public_ips\\.go', '\\berror handling\\b', '\\bwrong direction\\b', '\\bruled out\\b'))
    assert guilty


def test_penalizes_cluster_discovery_poller_absent_file():
    guilty = _trap_fires(load_answer(), ('cluster_discovery_poller',), ('(hinge|binds?|binding|source|cause|reason|responsible|explanation|is where|coupling|resolves? the binding|holds? the (binding|hinge|bug))',), ('\\bnot\\b', '\\bdoes not exist\\b', '\\babsent\\b', '\\bafter[- ]state\\b', '\\bpost[- ]?refactor\\b', '\\bafter the fix\\b', '\\badded by\\b', '\\bintroduc\\w*', '\\bnew\\b', '\\badjacent\\b', '\\bdoes \\*\\*not\\*\\* exist\\b'))
    assert guilty
