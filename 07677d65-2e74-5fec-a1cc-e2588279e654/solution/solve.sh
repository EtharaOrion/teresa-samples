#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/agent /logs/artifacts
cp /solution/answer.md /logs/agent/answer.md

python3 - <<'PYEOF'
import json, pathlib, subprocess

WORKDIR = '/workspace/hibernate__hibernate-orm'
COMMANDS = [
    'grep -H -n -A 20 TwoEntityQueryGenerator hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/TwoEntityQueryGenerator.java',
    'grep -H -n -A 20 build hibernate-envers/src/main/java/org/hibernate/envers/configuration/metadata/QueryGeneratorBuilder.java',
    'grep -H -n -A 20 addEntityAtRevisionRestriction hibernate-envers/src/main/java/org/hibernate/envers/strategy/DefaultAuditStrategy.java',
    'grep -H -n -A 20 addFromElement hibernate-core/src/main/java/org/hibernate/hql/internal/ast/tree/FromElementFactory.java',
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/configuration/metadata/QueryGeneratorBuilder.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/lazy/initializor/AbstractCollectionInitializor.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/RelationQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/TwoEntityQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/OneEntityQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/OneAuditEntityQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/TwoEntityOneAuditedQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/entities/mapper/relation/query/ThreeEntityQueryGenerator.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/query/impl/EntitiesAtRevisionQuery.java",
    "sed -n '1,2000p' hibernate-envers/src/main/java/org/hibernate/envers/tools/query/QueryBuilder.java",
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
