#!/bin/bash
set -uo pipefail

TRAJECTORY="${HG_TRAJECTORY:-/logs/agent/trajectory.json}"
ANSWER_FILE="${HG_ANSWER_FILE_IN:-/logs/agent/answer.md}"
PATCH="${HG_PATCH:-/logs/artifacts/agent.patch}"
REWARD="${HG_REWARD_OUT:-/logs/verifier/reward.json}"
TESTS_DIR="${HG_TESTS_DIR:-/tests}"
mkdir -p "$(dirname "${REWARD}")" /logs/verifier
[ -f "${PATCH}" ] || : > "${PATCH}"

python3 - <<'PYEOF'
from __future__ import annotations
import json, os, pathlib, re, subprocess, sys
from pathlib import Path
from typing import Any

AGENT_SOURCE = "agent"

_TEXT_KEYS = ("text", "content", "value")

def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if isinstance(part, dict):
        for key in _TEXT_KEYS:
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""

def message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        parts = [t for t in (_part_text(p) for p in message) if t.strip()]
        return "\n".join(parts)
    return _part_text(message)

def answer_from_events(events_dir: str | Path) -> str:
    d = Path(events_dir)
    if not d.is_dir():
        return ""

    def _key(p: Path) -> tuple[int, str]:
        try:
            return (int(p.stem), p.stem)
        except ValueError:
            return (1 << 30, p.stem)

    for f in sorted(d.glob("*.json"), key=_key, reverse=True):
        try:
            ev = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(ev, dict) or ev.get("action") != "finish":
            continue
        args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
        text = args.get("final_thought")
        if isinstance(text, str) and text.strip():
            return text
    return ""

def answer_from_trajectory(trajectory_path: str | Path) -> str:
    path = Path(trajectory_path)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return ""
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        return ""
    for step in reversed(steps):
        if not isinstance(step, dict) or step.get("source") != AGENT_SOURCE:
            continue
        text = message_text(step.get("message"))
        if text.strip():
            return text
    return ""

def find_events_dir(base: str | Path) -> Path | None:
    root = Path(base)
    if not root.exists():
        return None
    for cand in sorted(root.glob("sessions/*/events")):
        if cand.is_dir():
            return cand
    for cand in sorted(root.glob("**/sessions/*/events")):
        if cand.is_dir():
            return cand
    return None

def history_from_events(events_dir: str | Path) -> list[dict[str, Any]]:
    d = Path(events_dir)
    if not d.is_dir():
        return []

    def _key(p: Path) -> tuple[int, str]:
        try:
            return (int(p.stem), p.stem)
        except ValueError:
            return (1 << 30, p.stem)

    events: list[dict[str, Any]] = []
    for f in sorted(d.glob("*.json"), key=_key):
        try:
            ev = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(ev, dict):
            events.append(ev)
    return events

def _observation_text(obs: Any, tool_call_id: Any = None) -> str:
    if obs is None:
        return ""
    if isinstance(obs, str):
        return obs
    if not isinstance(obs, dict):
        return str(obs)

    results = obs.get("results")
    if isinstance(results, list):
        matched = [r for r in results if isinstance(r, dict)
                   and (tool_call_id is None or r.get("source_call_id") == tool_call_id)]
        if not matched:
            matched = [r for r in results if isinstance(r, dict)]
        return "\n".join(str(r.get("content") or r.get("text") or "") for r in matched)

    for key in ("content", "output", "text", "stdout"):
        if obs.get(key):
            return str(obs[key])
    return ""

def history_from_trajectory(trajectory_path: str | Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(trajectory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    events: list[dict[str, Any]] = []
    next_id = 1
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for call in step.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            args = call.get("arguments") or call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            name = str(call.get("function_name") or call.get("name")
                       or call.get("function") or "").lower()
            if name in ("read", "view", "open", "str_replace_editor", "file_read"):
                action = "read"
            elif name in ("edit", "write", "str_replace", "file_edit"):
                action = "edit"
            else:
                action = "run"
            events.append({
                "id": next_id, "source": "agent", "action": action,
                "args": args if isinstance(args, dict) else {"command": str(args)},
            })
            events.append({"observation": action, "cause": next_id,
                            "content": _observation_text(step.get("observation"),
                                                         call.get("tool_call_id"))})
            next_id += 1
    return events

TRAJ = os.environ.get("HG_TRAJECTORY", "/logs/agent/trajectory.json")
ANSWER_FILE = os.environ.get("HG_ANSWER_FILE_IN", "/logs/agent/answer.md")
PATCH = os.environ.get("HG_PATCH", "/logs/artifacts/agent.patch")
REWARD = os.environ.get("HG_REWARD_OUT", "/logs/verifier/reward.json")
TESTS = pathlib.Path(os.environ.get("HG_TESTS_DIR", "/tests"))
WORK = pathlib.Path("/tmp/teresa-verify"); WORK.mkdir(parents=True, exist_ok=True)

def read(p):
    try:
        return pathlib.Path(p).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "").strip()
JUDGE_API_KEY = os.environ.get("JUDGE_API_KEY", "").strip()
JUDGE_BASE_URL = (os.environ.get("JUDGE_BASE_URL", "").strip()
                  or "https://api.openai.com/v1")
JUDGE_ON = bool(JUDGE_MODEL and JUDGE_API_KEY)
JUDGE_CHUNK = 20


def _judge_chat(prompt):
    import time
    import urllib.request
    payload = json.dumps({
        "model": JUDGE_MODEL.split("/")[-1],
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    url = JUDGE_BASE_URL.rstrip("/") + "/chat/completions"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + JUDGE_API_KEY})
            with urllib.request.urlopen(req, timeout=180) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace"))
            return body["choices"][0]["message"]["content"] or ""
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(3)
    raise RuntimeError("judge request failed after 3 attempts: %r" % (last,))


def _extract_json_object(content):
    text = (content or "").strip()
    for candidate in (text,
                      re.sub("^```[a-zA-Z]*|```$", "", text, flags=re.M).strip()):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    match = re.search("[{].*[}]", text, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    return None


def _judge_verdicts(criteria, label, evidence):
    verdicts = {}
    for start in range(0, len(criteria), JUDGE_CHUNK):
        chunk = criteria[start:start + JUDGE_CHUNK]
        listing = "\n".join(
            "%s: %s" % (c.get("number"), c.get("criterion")) for c in chunk)
        prompt = (
            "You are grading an AI agent's work against rubric criteria.\n"
            "For EACH criterion decide whether the statement is TRUE of the "
            + label + " below. Some statements describe mistakes or flaws; "
            "answer true only when the flaw is genuinely present.\n\n"
            "Reply with ONLY a JSON object mapping each criterion id to true or "
            "false, for example {\"R1\": true, \"R2\": false}.\n\n"
            "=== " + label.upper() + " ===\n" + (evidence or "")[:120000]
            + "\n\n=== CRITERIA ===\n" + listing + "\n")
        parsed = None
        for attempt in range(3):
            content = _judge_chat(
                prompt if attempt == 0 else
                prompt + "\nReturn ONLY the JSON object. No prose, no code fence.\n")
            parsed = _extract_json_object(content)
            if parsed is not None:
                break
        if parsed is None:
            raise RuntimeError(
                "judge returned no JSON object for %s after 3 attempts" % label)
        for c in chunk:
            raw = parsed.get(str(c.get("number")))
            if isinstance(raw, bool):
                verdicts[c.get("number")] = raw
            else:
                verdicts[c.get("number")] = str(raw).strip().lower() in (
                    "true", "yes", "1")
    return verdicts


def _trajectory_digest(history):
    lines = []
    for event in history or []:
        if event.get("action"):
            args = event.get("args") or {}
            lines.append("$ %s" % (args.get("command") or args.get("path") or ""))
        elif event.get("content"):
            lines.append(str(event.get("content"))[:400])
    return "\n".join(lines)


def score_rubric(answer, history):
    criteria = json.loads(read(TESTS / "rubric.json") or "[]")
    if not criteria:
        return None, {}
    answer_criteria = [c for c in criteria
                       if c.get("evaluation_target") != "trajectory"]
    trajectory_criteria = [c for c in criteria
                           if c.get("evaluation_target") == "trajectory"]
    verdicts = {}
    if answer_criteria:
        verdicts.update(_judge_verdicts(answer_criteria, "response", answer))
    if trajectory_criteria:
        verdicts.update(_judge_verdicts(
            trajectory_criteria, "agent trajectory", _trajectory_digest(history)))
    total = sum(c.get("score", 0) for c in criteria if c.get("score", 0) > 0)
    earned = sum(c.get("score", 0) for c in criteria
                 if verdicts.get(c.get("number")))
    if total <= 0:
        return 0.0, verdicts
    return max(0.0, min(1.0, earned / total)), verdicts


def write_rubric_breakdown(rubric_value, verdicts):
    criteria = json.loads(read(TESTS / "rubric.json") or "[]")
    if not criteria:
        return
    rows = []
    for c in criteria:
        number = c.get("number")
        rows.append({
            "number": number,
            "met": bool(verdicts.get(number)),
            "score": c.get("score"),
            "is_positive": bool(c.get("is_positive", True)),
            "evaluation_target": c.get("evaluation_target"),
            "criterion": c.get("criterion"),
        })
    missed = [r["number"] for r in rows if r["is_positive"] and not r["met"]]
    tripped = [r["number"] for r in rows if not r["is_positive"] and r["met"]]
    payload = {
        "score": round(rubric_value, 4),
        "positive_total": sum(r["score"] for r in rows if (r["score"] or 0) > 0),
        "missed_positive": missed,
        "tripped_negative": tripped,
        "criteria": rows,
    }
    try:
        dest = pathlib.Path(REWARD).parent / "rubric_breakdown.json"
        dest.write_text(json.dumps(payload, indent=2) + chr(10), encoding="utf-8")
    except OSError as exc:
        print("[WARN] could not write rubric_breakdown.json: %r" % (exc,),
              file=sys.stderr)
    print("[rubric] missed positives: %s" % (", ".join(missed) or "none"))
    print("[rubric] tripped negatives: %s" % (", ".join(tripped) or "none"))


_ev = find_events_dir(os.path.dirname(TRAJ) or ".")
answer = answer_from_events(_ev) if _ev else ""
if not answer.strip() and os.path.exists(TRAJ):
    answer = answer_from_trajectory(TRAJ)
if not answer.strip():
    answer = read(ANSWER_FILE)

if not answer.strip():
    empty = ({"pytest": 0.0, "rubric": 0.0, "reward": 0.0} if JUDGE_ON
             else {"pytest": 0.0, "rubric_scored": 0})
    pathlib.Path(REWARD).write_text(json.dumps(empty) + chr(10))
    print("[info] no answer -> 0")
    raise SystemExit(0)

row = {
    "instance_id": os.environ.get("HG_INSTANCE_ID", ""),
    "test_result": {"answer": {"text": answer}, "git_patch": read(PATCH)},
}
events = find_events_dir(os.path.dirname(TRAJ) or ".")
history = history_from_events(events) if events else []
src = "events"
if not history and os.path.exists(TRAJ):
    history = history_from_trajectory(TRAJ)
    src = "trajectory(atif)"
if history:
    row["history"] = history
    print("[info] history: %d events from %s" % (len(history), src))
row_path = WORK / "output.jsonl"
row_path.write_text(json.dumps(row, default=str) + chr(10), encoding="utf-8")

target = TESTS / "test_output.py"
if not target.exists():
    print("[FATAL] missing", target, file=sys.stderr)
    raise SystemExit(2)

env = dict(os.environ)
env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
env["HG_OUTPUT_JSONL"] = str(row_path)
env["PYTHONDONTWRITEBYTECODE"] = "1"
env.pop("HG_ANSWER_FILE", None)
env.pop("HG_PATCH_FILE", None)

proc = subprocess.run(
    [sys.executable, "-m", "pytest", str(target), "-v",
     "-p", "no:cacheprovider", "--rootdir", str(TESTS)],
    cwd=str(TESTS), capture_output=True, text=True, env=env)
stdout = (proc.stdout or "") + (proc.stderr or "")

_W = chr(92) + "w"
_OB = chr(92) + "["
_CB = chr(92) + "]"
_S = chr(92) + "s"
NODE = re.compile("::(?P<name>[" + _W + _OB + _CB + "<>-]+)" + _S + "+"
                  "(?P<status>PASSED|FAILED|ERROR|XPASS|XFAIL|SKIPPED)")
PASS = {"PASSED", "XPASS"}
outcomes = {m.group("name"): m.group("status") for m in NODE.finditer(stdout)}
if not outcomes:
    print("[FATAL] pytest produced no outcomes (rc=%d)" % proc.returncode, file=sys.stderr)
    print(stdout[-1500:], file=sys.stderr)
    raise SystemExit(2)

weights = json.loads(read(TESTS / "test_weights.json") or "{}")
if weights:
    total = sum(w for w in weights.values() if w > 0)
    earned = sum(w for n, w in weights.items() if outcomes.get(n) in PASS)
    value = max(0.0, min(1.0, earned / total)) if total > 0 else 0.0
else:
    passed = sum(1 for v in outcomes.values() if v in PASS)
    value = passed / len(outcomes)

reward_out = {"pytest": value, "rubric_scored": 0}
rubric_value = None
rubric_verdicts = {}
if JUDGE_ON:
    try:
        rubric_value, rubric_verdicts = score_rubric(answer, history)
    except Exception as exc:
        print("[WARN] rubric not scored: %r" % (exc,), file=sys.stderr)
        rubric_value = None
    if rubric_value is not None:
        reward_out = {"pytest": round(value, 4),
                      "rubric": round(rubric_value, 4),
                      "reward": round((value + rubric_value) / 2.0, 4)}
        write_rubric_breakdown(rubric_value, rubric_verdicts)

pathlib.Path(REWARD).write_text(
    json.dumps(reward_out) + chr(10), encoding="utf-8")
for n, w in sorted(weights.items()):
    print("  %-46s %-7s w=%s" % (n, outcomes.get(n, "MISSING"), w))
if rubric_value is None:
    print("[ok] pytest=%.4f  (process channel only -- rubric scores the answer)" % value)
else:
    print("[ok] pytest=%.4f  rubric=%.4f  reward=%.4f"
          % (value, rubric_value, reward_out["reward"]))
PYEOF
status=$?
cat "${REWARD}" 2>/dev/null
exit $status
