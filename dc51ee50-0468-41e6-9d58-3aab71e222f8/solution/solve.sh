#!/usr/bin/env bash
# Oracle: emit the reference answer so an OracleAgent run scores a passing reward.
# The gold answer is shipped inside /solution (mounted during the oracle agent phase);
# /tests is NOT mounted until the verifier runs, so the oracle must read from /solution.
set -euo pipefail
mkdir -p /logs/agent
cp /solution/answer.md /logs/agent/answer.md
cat /solution/answer.md
