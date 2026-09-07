#!/usr/bin/env bash
# Harbor verifier entrypoint. Writes a numeric reward in [0,1] to
# /logs/verifier/reward.json (flat dict; reward.json wins over reward.txt).
#
# Deterministic layer: the bundle's pytest module grades the agent answer/patch.
# HG_OUTPUT_JSONL points the tests at the rollout row (the harness seam).
set -uo pipefail
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# Point the tests at the rollout row only when it actually exists. A missing-but-set
# HG_OUTPUT_JSONL makes test_output.py open() a nonexistent file and crash every test;
# oracle/noop agents never write output.jsonl, so the bundle's /logs/agent/answer.md
# fallback must stay reachable. A real agent run writes output.jsonl and still wins.
if [ -n "${HG_OUTPUT_JSONL:-}" ] && [ ! -f "${HG_OUTPUT_JSONL}" ]; then
  unset HG_OUTPUT_JSONL
fi
if [ -z "${HG_OUTPUT_JSONL:-}" ] && [ -f /logs/agent/output.jsonl ]; then
  export HG_OUTPUT_JSONL=/logs/agent/output.jsonl
fi

python -m pytest /tests/test_output.py -v > /logs/verifier/test-stdout.txt 2>&1
# Full parity (reward = mean(rubric, pytest)) additionally runs the rubric judge here
# under environment_mode="separate" (network-enabled verifier env). See HARBOR_ADAPTER_PLAN.md section 6.
# The teresa grader computes the blended reward; this script records the deterministic result.
python - <<'PY'
import json, re, pathlib
# Mirror criteria.py PytestCriterion: weight by test_weights.json, dividing by the
# POSITIVE-weight total only. A flat passed/total is wrong whenever the bundle carries a
# negative penalty test -- read_only_respected and modified_code_penalty are exact
# complements, so exactly one always fails and a flat ratio caps a perfect answer below 1.0.
out = pathlib.Path("/logs/verifier/test-stdout.txt").read_text() if pathlib.Path("/logs/verifier/test-stdout.txt").exists() else ""
PASS = {"PASSED", "XPASS"}
outcomes = dict(re.findall(r"::(test_\w+)\s+(PASSED|FAILED|ERROR|SKIPPED|XPASS|XFAIL)", out))
wpath = pathlib.Path("/tests/test_weights.json")
weights = {}
if wpath.exists():
    try:
        loaded = json.loads(wpath.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            weights = {k: float(v) for k, v in loaded.items()}
    except (ValueError, TypeError):
        weights = {}
if weights:
    total = sum(w for w in weights.values() if w > 0)
    earned = sum(w for name, w in weights.items() if outcomes.get(name) in PASS)
    reward = max(0.0, min(1.0, earned / total)) if total > 0 else 0.0
else:
    passed = sum(1 for s in outcomes.values() if s in PASS)
    reward = (passed / len(outcomes)) if outcomes else 0.0
pathlib.Path("/logs/verifier/reward.json").write_text(json.dumps({"reward": round(reward, 4)}))
PY
