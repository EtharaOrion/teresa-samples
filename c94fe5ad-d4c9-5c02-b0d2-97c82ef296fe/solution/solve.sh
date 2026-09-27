#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/agent /logs/artifacts
cp /solution/answer.md /logs/agent/answer.md

python3 - <<'PYEOF'
import json, pathlib, subprocess

WORKDIR = '/workspace/swc-project__swc'
COMMANDS = [
    'grep -H -n -A 20 default_constructor crates/swc_ecma_utils/src/lib.rs',
    'grep -H -n -A 20 srcmap crates/swc_ecma_codegen/src/macros.rs',
    "grep -rn --include='*.rs' 'default_constructor(' crates",
    "grep -n -A 60 'pub(super) fn fold_constructor(' crates/swc_ecma_compat_es2015/src/classes/constructor.rs",
    "sed -n '1,2000p' crates/swc_common/src/source_map.rs",
    "sed -n '1,2000p' crates/swc_ecma_codegen/src/lib.rs",
    "sed -n '1,2000p' crates/swc_ecma_compat_es2015/src/classes/constructor.rs",
    "sed -n '1,2000p' crates/swc_ecma_compat_es2015/src/classes/mod.rs",
    "sed -n '1,2000p' crates/swc_ecma_compat_es2022/src/class_properties/mod.rs",
    "sed -n '1,2000p' crates/swc_ecma_compat_es2022/src/private_in_object.rs",
    "sed -n '1,2000p' crates/swc_ecma_transforms_compat/src/class_fields_use_set.rs",
    "sed -n '1,2000p' crates/swc_ecma_transforms_proposal/src/decorator_impl.rs",
    "sed -n '1,2000p' crates/swc_ecma_transforms_proposal/src/decorators/mod.rs",
    "sed -n '1,2000p' crates/swc_ecma_utils/src/constructor.rs",
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
