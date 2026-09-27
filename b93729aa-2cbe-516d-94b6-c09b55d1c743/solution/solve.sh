#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/agent /logs/artifacts
cp /solution/answer.md /logs/agent/answer.md

python3 - <<'PYEOF'
import json, pathlib, subprocess

WORKDIR = '/workspace/boundless-xyz__boundless'
COMMANDS = [
    "grep -H -n -F -A 20 'async fn estimate_gas_to_fulfill(' crates/boundless-market/src/prover_utils/mod.rs",
    "grep -H -n -F -A 20 'async fn price_order(' crates/boundless-market/src/prover_utils/mod.rs",
    "grep -H -n -F -A 20 'async fn calculate_exec_limits(' crates/boundless-market/src/prover_utils/mod.rs",
    "grep -H -n -F -A 20 'pub(crate) async fn estimate_gas_to_fulfill(' crates/broker/src/utils/helpers.rs",
    "grep -H -n -F -A 20 'fn submission_path_for_risc0_selector(selector: FixedBytes<4>) -> SubmissionPath {' crates/risc0-backend/src/lib.rs",
    "grep -H -n -F -A 20 'async fn prove_and_update_db(&self, mut order: Order) {' crates/broker/src/order_processor/service.rs",
    "sed -n '1,2000p' crates/boundless-backend/src/router.rs",
    "sed -n '1,2000p' crates/boundless-backend/src/router_policy.rs",
    "sed -n '1,2000p' crates/boundless-backend/src/types.rs",
    "sed -n '1,2000p' crates/boundless-market/src/contracts/fulfillment_batch.rs",
    "sed -n '1,2000p' crates/boundless-market/src/contracts/mod.rs",
    "sed -n '1,2000p' crates/boundless-market/src/prover_utils/requestor_pricing.rs",
    "sed -n '1,2000p' crates/boundless-market/src/selector.rs",
    "sed -n '1,2000p' crates/broker/src/order_locker/service.rs",
    "sed -n '1,2000p' crates/broker/src/order_pricer/helpers.rs",
    "sed -n '1,2000p' crates/broker/src/utils/mod.rs",
    'grep -rn groth16_verify_gas_estimate .',
]

steps = []
for i, cmd in enumerate(COMMANDS, start=1):
    proc = subprocess.run(['bash', '-lc', cmd], cwd=WORKDIR,
                          capture_output=True, text=True)
    steps.append({
        'step_id': i,
        'source': 'agent',
        'message': '',
        'tool_calls': [{'tool_call_id': 'call_%d' % i, 'name': 'bash',
                        'arguments': {'command': cmd}}],
        'observation': {'content': (proc.stdout or '') + (proc.stderr or '')},
    })

answer = pathlib.Path('/solution/answer.md').read_text(encoding='utf-8')
steps.append({'step_id': len(steps) + 1, 'source': 'agent', 'message': answer})
pathlib.Path('/logs/agent/trajectory.json').write_text(
    json.dumps({'steps': steps}, indent=1), encoding='utf-8')
print('[oracle] %d commands executed, trajectory written' % len(COMMANDS))
PYEOF

cat /logs/agent/answer.md
