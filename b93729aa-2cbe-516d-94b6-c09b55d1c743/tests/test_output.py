from __future__ import annotations

import json
import os
import re
import shlex

GOLDEN = {'language': 'rust',
 'targets': [{'name': 'test_read_estimate_gas_to_fulfill_in_mod',
              'files': ['crates/boundless-market/src/prover_utils/mod.rs'],
              'function': 'estimate_gas_to_fulfill',
              'def_lines': ['async fn estimate_gas_to_fulfill('],
              'weight': 5},
             {'name': 'test_read_price_order_in_mod',
              'files': ['crates/boundless-market/src/prover_utils/mod.rs'],
              'function': 'price_order',
              'def_lines': ['    async fn price_order('],
              'weight': 3},
             {'name': 'test_read_calculate_exec_limits_in_mod',
              'files': ['crates/boundless-market/src/prover_utils/mod.rs'],
              'function': 'calculate_exec_limits',
              'def_lines': ['    async fn calculate_exec_limits('],
              'weight': 3},
             {'name': 'test_read_estimate_gas_to_fulfill_in_helpers',
              'files': ['crates/broker/src/utils/helpers.rs'],
              'function': 'estimate_gas_to_fulfill',
              'def_lines': ['pub(crate) async fn estimate_gas_to_fulfill('],
              'weight': 3},
             {'name': 'test_read_submission_path_for_risc0_selector_in_lib',
              'files': ['crates/risc0-backend/src/lib.rs'],
              'function': 'submission_path_for_risc0_selector',
              'def_lines': ['fn submission_path_for_risc0_selector(selector: FixedBytes<4>) -> '
                            'SubmissionPath {'],
              'weight': 3},
             {'name': 'test_read_prove_and_update_db_in_service',
              'files': ['crates/broker/src/order_processor/service.rs'],
              'function': 'prove_and_update_db',
              'def_lines': ['    async fn prove_and_update_db(&self, mut order: Order) {'],
              'weight': 3},
             {'name': 'test_opened_router',
              'files': ['crates/boundless-backend/src/router.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_router_policy',
              'files': ['crates/boundless-backend/src/router_policy.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_types',
              'files': ['crates/boundless-backend/src/types.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_fulfillment_batch',
              'files': ['crates/boundless-market/src/contracts/fulfillment_batch.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_mod',
              'files': ['crates/boundless-market/src/contracts/mod.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_requestor_pricing',
              'files': ['crates/boundless-market/src/prover_utils/requestor_pricing.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_selector',
              'files': ['crates/boundless-market/src/selector.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_service',
              'files': ['crates/broker/src/order_locker/service.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_helpers',
              'files': ['crates/broker/src/order_pricer/helpers.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1},
             {'name': 'test_opened_mod_utils',
              'files': ['crates/broker/src/utils/mod.rs'],
              'function': None,
              'def_lines': [],
              'weight': 1}],
 'symbols': [{'name': 'test_searched_groth16_verify_gas_estimate',
              'symbol': 'groth16_verify_gas_estimate',
              'weight': 1}],
 'external_prefixes': ['alloy',
                       'alloy_chains',
                       'alloy_consensus_any',
                       'alloy_contract',
                       'alloy_node_bindings',
                       'alloy_primitives',
                       'alloy_provider',
                       'alloy_signer',
                       'alloy_sol_types',
                       'anyhow',
                       'ark_bn254',
                       'ark_ff',
                       'ark_groth16',
                       'ark_serialize',
                       'assert_cmd',
                       'assert_fs',
                       'astral_tokio_tar',
                       'async_channel',
                       'async_compression',
                       'async_stream',
                       'async_trait',
                       'atomicwrites',
                       'auto_impl',
                       'aws',
                       'aws-lambda',
                       'aws_config',
                       'aws_credential_types',
                       'aws_sdk_cloudwatch',
                       'aws_sdk_kinesis',
                       'aws_sdk_s3',
                       'aws_smithy_types',
                       'awsx',
                       'axum',
                       'axum_extra',
                       'base64',
                       'bincode',
                       'blake3',
                       'blst',
                       'bonsai_sdk',
                       'borsh',
                       'bs58',
                       'bytemuck',
                       'bytes',
                       'chrono',
                       'circom_witnesscalc',
                       'clap',
                       'clap_complete',
                       'client-cloudwatch',
                       'client-ecs',
                       'client-sts',
                       'colored',
                       'criterion',
                       'csv',
                       'dashmap',
                       'deadpool_redis',
                       'derive_builder',
                       'dirs',
                       'docker-build',
                       'dotenv',
                       'elsa',
                       'esbuild',
                       'fdir',
                       'futures',
                       'futures_util',
                       'google_cloud_auth',
                       'google_cloud_gax',
                       'google_cloud_storage',
                       'guest_set_builder',
                       'hex',
                       'httpmock',
                       'hyper_util',
                       'inquire',
                       'jest',
                       'jsurl',
                       'lambda_http',
                       'lambda_runtime',
                       'lazy_static',
                       'libc',
                       'liblzma',
                       'log',
                       'memmap2',
                       'moka',
                       'nix',
                       'node',
                       'notify',
                       'num_bigint',
                       'num_cpus',
                       'num_enum',
                       'num_traits',
                       'openssl',
                       'postcard',
                       'predicates',
                       'prometheus',
                       'prometheus_exporter',
                       'proptest',
                       'proptest_derive',
                       'pulumi',
                       'rand',
                       'redis',
                       'regex',
                       'reqwest',
                       'risc0_aggregation',
                       'risc0_binfmt',
                       'risc0_build',
                       'risc0_build_ethereum',
                       'risc0_circuit_recursion',
                       'risc0_ethereum_contracts',
                       'risc0_groth16',
                       'risc0_groth16_sys',
                       'risc0_povw',
                       'risc0_steel',
                       'risc0_zkp',
                       'risc0_zkvm',
                       'rlimit',
                       'rmp_serde',
                       'ruint',
                       'rustls',
                       's3s',
                       's3s_fs',
                       'sample_guest_common',
                       'sample_guest_methods',
                       'serde',
                       'serde_bytes',
                       'serde_json',
                       'serde_yaml',
                       'serial_test',
                       'sha2',
                       'shadow_rs',
                       'signal_hook',
                       'siwe',
                       'sqlx',
                       'temp_env',
                       'tempfile',
                       'test_log',
                       'thiserror',
                       'time',
                       'tokio',
                       'tokio_test',
                       'tokio_tungstenite',
                       'tokio_util',
                       'toml',
                       'toml_edit',
                       'tower',
                       'tower_http',
                       'tracing',
                       'tracing_subscriber',
                       'tracing_test',
                       'ts-jest',
                       'typescript',
                       'url',
                       'urlencoding',
                       'utoipa',
                       'utoipa_axum',
                       'utoipa_swagger_ui',
                       'uuid',
                       'wiremock',
                       'wtns_file',
                       'xshell'],
 'process_weights': {'answer_grounded': 3, 'modified_code_penalty': -5}}

_JSONL_ENV = 'HG_OUTPUT_JSONL'

INVALID = object()

def _reject_dupes(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f'duplicate key {k!r}')
        seen[k] = v
    return seen

def _load_row():
    path = os.environ.get(_JSONL_ENV)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError:
        return INVALID
    if len(lines) != 1:
        return INVALID
    try:
        row = json.loads(lines[0], object_pairs_hook=_reject_dupes)
    except ValueError:
        return INVALID
    return row if isinstance(row, dict) else INVALID

_ROW_CACHE = []

def _row():
    if not _ROW_CACHE:
        _ROW_CACHE.append(_load_row())
    return _ROW_CACHE[0]

def _usable_row():
    r = _row()
    return r if isinstance(r, dict) else None

def _result() -> dict:
    r = _usable_row()
    if r is None:
        return {}
    tr = r.get('test_result')
    return tr if isinstance(tr, dict) else {}

def _answer() -> str:
    a = _result().get('answer')
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        t = a.get('text')
        return t if isinstance(t, str) else ''
    return ''

_WS_PREFIX = re.compile(r'^(?:/+(?:workspace|workdir|repo|src|home/[^/]+|testbed)(?:/+[^/]+)?)/+')

def _norm_rel(p: str, cwd: str = '') -> str:
    p = (p or '').strip().strip('"').strip("'").replace('\\', '/')
    if not p:
        return ''
    if p.startswith('/'):
        p = _WS_PREFIX.sub('', p)
        p = p.lstrip('/')
    elif cwd:
        p = cwd.rstrip('/') + '/' + p
        if p.startswith('/'):
            p = _WS_PREFIX.sub('', p).lstrip('/')
    parts = []
    for seg in p.split('/'):
        if seg in ('', '.'):
            continue
        if seg == '..':
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return '/'.join(parts)

def _same_path(observed: str, target: str) -> bool:
    o, t = _norm_rel(observed), target.strip('/')
    if not o or not t:
        return False
    return o == t or o.endswith('/' + t)

_CD = re.compile(r'^\s*cd\s+([^\s;&|]+)\s*(?:&&|;)\s*(.*)$', re.DOTALL)
_BARE_CD = re.compile(r'^\s*cd\s+([^\s;&|]+)\s*$')

_SEG_SPLIT = re.compile(r'\|\||&&|(?<!\\)[|;\n]')

_DISPLAY_VERBS = (
    'cat', 'bat', 'nl', 'head', 'tail', 'less', 'more', 'sed', 'awk', 'grep', 'egrep',
    'fgrep', 'rg', 'ripgrep', 'view', 'open', 'type', 'perl', 'python', 'python3', 'ruby',
)
_LISTING_VERBS = ('find', 'ls', 'tree', 'locate', 'fd', 'dir', 'stat', 'file', 'wc', 'du')

_OPTION = re.compile(r'^-')
_PATHY = re.compile(r'^[\w@./+-]+$')

_ERROR_OUT = re.compile(
    r'(?m)^(?:[^\n:]{0,200}:\s*){0,3}(?:no such file or directory|does not exist|not a directory'
    r'|is a directory|permission denied|command not found|cannot open|cannot access'
    r'|no matches found|fatal:|usage:|invalid option|error:\s*the path|binary file)',
    re.IGNORECASE)

def _tokens(seg: str):
    try:
        return shlex.split(seg)
    except ValueError:
        return seg.split()

def _segment_files(seg: str, cwd: str):
    toks = _tokens(seg)
    if not toks:
        return [], False
    verb = os.path.basename(toks[0])
    if verb in ('sudo', 'time', 'env', 'nohup', 'xargs') and len(toks) > 1:
        toks = toks[1:]
        verb = os.path.basename(toks[0])
    if verb == 'git':
        if len(toks) > 2 and toks[1] in ('show', 'cat-file'):
            out = []
            for t in toks[2:]:
                if ':' in t and not _OPTION.match(t):
                    out.append(_norm_rel(t.split(':', 1)[1], cwd))
            return [p for p in out if p], False
        if len(toks) > 1 and toks[1] == 'grep':
            return [], True
        return [], False
    if verb in _LISTING_VERBS:
        return [], False
    if verb not in _DISPLAY_VERBS:
        return [], False
    is_search = verb in ('grep', 'egrep', 'fgrep', 'rg', 'ripgrep', 'ag', 'ack')
    rest = toks[1:]
    if verb in ('perl', 'python', 'python3', 'ruby'):
        m = re.search(r'open\s*\(\s*[\'"]([^\'"]+)[\'"]', seg)
        return ([_norm_rel(m.group(1), cwd)] if m else []), False
    operands, skip_next = [], False
    for i, t in enumerate(rest):
        if skip_next:
            skip_next = False
            continue
        if _OPTION.match(t):
            if t in ('-e', '--regexp', '-f', '--file', '-m', '--max-count', '-A', '-B', '-C',
                     '--include', '--exclude', '--glob', '-g', '-t', '--type'):
                skip_next = True
            continue
        operands.append(t)
    if is_search:
        has_e = any(t in ('-e', '--regexp') for t in rest)
        if not has_e and operands:
            operands = operands[1:]
    if verb in ('sed', 'awk') and operands:
        operands = operands[1:]
    files = [_norm_rel(t, cwd) for t in operands if _PATHY.match(t)]
    return [f for f in files if f and not f.endswith('/')], is_search

def _iter_events():
    r = _usable_row()
    if r is None:
        return []
    hist = r.get('history')
    if not isinstance(hist, list):
        return []
    return [e for e in hist if isinstance(e, dict)]

def _calls():
    hist = _iter_events()
    obs = {}
    for e in hist:
        if e.get('observation') and e.get('cause') is not None:
            obs.setdefault(e['cause'], str(e.get('content') or ''))
    out, cwd = [], ''
    for e in hist:
        if e.get('source') != 'agent':
            continue
        action = e.get('action')
        if action == 'finish':
            break
        args = e.get('args')
        args = args if isinstance(args, dict) else {}
        content = obs.get(e.get('id'), '')
        if action == 'run':
            cmd = str(args.get('command') or '')
            bare = _BARE_CD.match(cmd)
            if bare:
                cwd = _norm_rel(bare.group(1), cwd)
                continue
            m = _CD.match(cmd)
            if m:
                cwd = _norm_rel(m.group(1), cwd)
                cmd = m.group(2)
            out.append(('run', cmd, content, cwd))
        elif action in ('read', 'view'):
            out.append(('read', _norm_rel(str(args.get('path') or ''), cwd), content, cwd))
        elif action == 'edit':
            continue
        else:
            cmd = args.get('command') or args.get('cmd')
            path = args.get('path') or args.get('file_path') or args.get('filename')
            if isinstance(cmd, str) and cmd:
                out.append(('run', cmd, content, cwd))
            elif isinstance(path, str) and path:
                out.append(('read', _norm_rel(path, cwd), content, cwd))
    return out

def _is_listing_only(out: str) -> bool:
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return True
    return all(re.fullmatch(r'[\w@./+-]+', ln) for ln in lines)

def _grep_hits(out: str):
    hits = []
    for ln in out.splitlines():
        m = re.match(r'^([\w@./+-]+):(\d+)[:-](.*)$', ln)
        if m:
            hits.append((m.group(1), m.group(3)))
    return hits

def _header_slices(out: str):
    parts = re.split(r'(?m)^==>\s+(.+?)\s+<==\s*$', out)
    if len(parts) < 3:
        return {}
    slices = {}
    for i in range(1, len(parts) - 1, 2):
        slices.setdefault(parts[i], '')
        slices[parts[i]] += parts[i + 1]
    return slices

def _displays_of(files):
    targets = [f.strip('/') for f in files]
    for kind, cmd, out, cwd in _calls():
        if not out.strip() or _ERROR_OUT.search(out) or _is_listing_only(out):
            continue
        if kind == 'read':
            if any(_same_path(cmd, t) for t in targets):
                yield out
            continue
        hits = _grep_hits(out)
        if hits:
            text = '\n'.join(t for p, t in hits if any(_same_path(p, tg) for tg in targets))
            if text.strip():
                yield text
                continue
        headers = _header_slices(out)
        if headers:
            for p, text in headers.items():
                if any(_same_path(p, t) for t in targets) and text.strip():
                    yield text
            continue
        shown = []
        for seg in _SEG_SPLIT.split(cmd):
            seg_files, _is_search = _segment_files(seg, cwd)
            shown.extend(seg_files)
        matched = [f for f in shown if any(_same_path(f, t) for t in targets)]
        if not matched:
            continue
        yield out

def _norm_line(s: str) -> str:
    return re.sub(r'\s+', ' ', s.strip())

def _shows_definition(out: str, def_lines) -> bool:
    if not def_lines:
        return False
    seen = {_norm_line(ln) for ln in out.splitlines() if ln.strip()}
    seen |= {_norm_line(re.sub(r'^\s*\d+[:\t ]\s?', '', ln)) for ln in out.splitlines() if ln.strip()}
    return any(_norm_line(d) in seen for d in def_lines)

_DEF_FORMS = {
    'rust': [r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:default\s+|const\s+|async\s+|unsafe\s+|extern\s+"[^"]*"\s+)*fn\s+{n}\b',
             r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union|type|mod)\s+{n}\b',
             r'^\s*impl(?:<[^>]*>)?\s+(?:\S+\s+for\s+)?{n}\b',
             r'^\s*(?:pub(?:\([^)]*\))?\s+)?(?:static|const)\s+{n}\s*:'],
    'typescript': [r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s+{n}\b',
                   r'^\s*(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:class|interface|enum|type)\s+{n}\b',
                   r'^\s*(?:export\s+)?(?:const|let|var)\s+{n}\s*(?::[^=]+)?=\s*(?:async\s*)?(?:function|\(|<|[\w$]+\s*=>)',
                   r'^\s*(?:public|private|protected|static|readonly|abstract|async|get|set|\s)*{n}\s*(?:<[^>]*>)?\s*\([^)]*\)\s*(?::[^{{;]+)?\{{',
                   r'^\s*(?:public|private|protected|static|readonly|\s)*{n}\s*(?::[^=]+)?=\s*(?:async\s*)?\(',
                   r'^\s*import\s+(?:type\s+)?[^;\n]*\b{n}\b[^;\n]*\bfrom\b'],
    'python': [r'^\s*(?:async\s+)?def\s+{n}\b', r'^\s*class\s+{n}\b', r'^\s*{n}\s*(?::[^=]+)?='],
    'go': [r'^\s*func\s+(?:\([^)]*\)\s*)?{n}\b', r'^\s*type\s+{n}\b'],
    'java': [r'^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*[\w<>\[\],.?\s]+\s+{n}\s*\(',
             r'^\s*(?:public|private|protected|static|final|abstract|\s)*(?:class|interface|enum|record)\s+{n}\b'],
}
_VARIANT_FORMS = {
    'rust': [r'^\s*(?:pub(?:\([^)]*\))?\s+)?{n}\s*:\s*\S',
             r'^\s*{n}\s*(?:\{{|\(|,\s*$)'],
    'typescript': [r'^\s*(?:readonly\s+)?{n}\s*[?!]?\s*:\s*\S'],
    'go': [r'^\s*{n}\s+[\w*\[\]]'],
    'python': [],
    'java': [],
}
_VARIANT_FORMS['javascript'] = _VARIANT_FORMS['typescript']
for _lang, _forms in _VARIANT_FORMS.items():
    _DEF_FORMS.setdefault(_lang, [])
    _DEF_FORMS[_lang] = _DEF_FORMS[_lang] + _forms

_DEF_FORMS['javascript'] = _DEF_FORMS['typescript']
_DEF_FORMS['tsx'] = _DEF_FORMS['typescript']
_DEF_FORMS['rs'] = _DEF_FORMS['rust']

def _def_regex(name: str):
    forms = _DEF_FORMS.get(str(GOLDEN.get('language', '')).lower()) or []
    if not forms:
        forms = sum(_DEF_FORMS.values(), [])
    n = re.escape(re.split(r'::|#|\.', name)[-1])
    return re.compile('|'.join(f.replace('{n}', n).replace('{{', '{').replace('}}', '}')
                               for f in forms), re.MULTILINE)

def _make_target_test(t: dict):
    files, fn, defs = t['files'], t.get('function'), t.get('def_lines') or []
    label = ' or '.join(files)
    if fn:
        def test():
            assert any(_shows_definition(out, defs) for out in _displays_of(files)), \
                f'the definition of {fn} in {label} was never displayed'
        test.__doc__ = f'The agent displayed the definition of {fn} in {label}.'
    else:
        def test():
            assert any(True for _ in _displays_of(files)), \
                f'{label} was never displayed (contents shown, not merely listed)'
        test.__doc__ = f'The agent displayed the contents of {label}.'
    test.__name__ = t['name']
    return test

for _t in GOLDEN.get('targets', []):
    globals()[_t['name']] = _make_target_test(_t)

_SEARCH_VERBS = ('grep', 'egrep', 'fgrep', 'rg', 'ripgrep', 'ag', 'ack')
_PAT_OPTS = ('-e', '--regexp', '--pattern')

def _search_patterns():
    pats = []
    for kind, cmd, _out, _cwd in _calls():
        if kind != 'run':
            continue
        for seg in _SEG_SPLIT.split(cmd):
            toks = _tokens(seg)
            if not toks:
                continue
            verb = os.path.basename(toks[0])
            rest = toks[1:]
            if verb == 'git':
                if len(rest) and rest[0] == 'grep':
                    rest = rest[1:]
                else:
                    continue
            elif verb not in _SEARCH_VERBS:
                continue
            taken, skip = None, False
            for i, t in enumerate(rest):
                if skip:
                    skip = False
                    continue
                if t in _PAT_OPTS and i + 1 < len(rest):
                    taken = rest[i + 1]
                    break
                if _OPTION.match(t):
                    if t in ('-f', '--file', '-m', '--max-count', '-A', '-B', '-C',
                             '--include', '--exclude', '--glob', '-g', '-t', '--type'):
                        skip = True
                    continue
                taken = t
                break
            if taken:
                pats.append(taken)
    return pats

def _make_symbol_test(s: dict):
    sym = s['symbol']

    def test():
        for p in _search_patterns():
            if re.search(r'(?<![\w$]){0}(?![\w$])'.format(re.escape(sym)), p):
                return
            try:
                if re.search(p, sym):
                    return
            except re.error:
                pass
        raise AssertionError(f'{sym} was never the argument of a search')
    test.__name__ = s['name']
    test.__doc__ = f'The agent searched the tree for {sym}.'
    return test

for _s in GOLDEN.get('symbols', []):
    globals()[_s['name']] = _make_symbol_test(_s)

_SRC_EXT = (r'\.(?:rs|ts|tsx|js|jsx|mjs|cjs|py|pyi|go|java|kt|rb|c|cc|cpp|h|hpp|scala|cs'
            r'|swift|php|proto|toml|yaml|yml|json|sql|move|vue|svelte|sh)')
_CITED_PATH = re.compile(r'(?<![\w/])((?:[\w@.+-]+/)+[\w@.+-]+' + _SRC_EXT + r')(?![\w])')
_CITED_DIR = re.compile(r'(?<![\w/])((?:[\w@.+-]+/){1,}[\w@.+-]*)(?=[\s`,)\]]|$)')
_CITED_FN = re.compile(r'`([A-Za-z_][\w:.#$]*\s*(?:\(\))?)`')
_PROSE = {'the', 'this', 'that', 'and', 'for', 'with', 'from', 'when', 'then', 'which',
          'where', 'while', 'into', 'true', 'false', 'null', 'none', 'self', 'return'}
_GOLDEN_FNS = {re.split(r'::|#|\.', t['function'])[-1]
               for t in GOLDEN.get('targets', []) if t.get('function')}

def _cited_paths(answer: str):
    return {_norm_rel(m.group(1)) for m in _CITED_PATH.finditer(answer)}

_STD_PREFIXES = {'std', 'core', 'alloc', 'libc', 'os', 'sys', 'fs', 'io', 'json',
                 'math', 'time', 'process', 'console', 'window', 'document', 'node'}
_GLOBALS = {'globalthis', 'reflect', 'promise', 'object', 'array', 'string', 'number',
            'boolean', 'symbol', 'proxy', 'map', 'set', 'error', 'date', 'regexp'}

def _cited_routines(answer: str):
    external = ({str(p).lower() for p in GOLDEN.get('external_prefixes', [])}
                | _STD_PREFIXES | _GLOBALS)
    out = set()
    for m in _CITED_FN.finditer(answer):
        raw = m.group(1).strip()
        called = raw.endswith('()')
        if called:
            raw = raw[:-2].strip()
        if re.search(_SRC_EXT + r'$', raw) or '/' in raw:
            continue
        parts = re.split(r'::|#|\.', raw)
        if any(p.lower().replace('-', '_') in external for p in parts[:-1]):
            continue
        if len(parts) > 1 and '::' not in raw and not parts[-2][:1].isupper():
            continue
        name = parts[-1]
        if not (len(name) >= 3 and name.lower() not in _PROSE
                and name.lower() not in _GLOBALS and not name.isupper()):
            continue
        if not (called or len(parts) > 1 or name in _GOLDEN_FNS):
            continue
        if len(parts) > 1 and name[:1].isupper():
            if name in _GOLDEN_FNS:
                out.add(((name, parts[-2]), True))
            continue
        out.add(((name,) + tuple(parts[-2:-1]), name in _GOLDEN_FNS))
    return out

_LINENO_PREFIX = re.compile(r'(?m)^\d+[:-]')

def _strip_line_numbers(text: str) -> str:
    return _LINENO_PREFIX.sub('', text)

def _any_display_slices():
    for kind, cmd, out, cwd in _calls():
        if not out.strip() or _ERROR_OUT.search(out) or _is_listing_only(out):
            continue
        if kind == 'read':
            yield _norm_rel(cmd), _strip_line_numbers(out)
            continue
        hits = _grep_hits(out)
        if hits:
            by_path = {}
            for p, text in hits:
                by_path.setdefault(_norm_rel(p), []).append(text)
            for p, texts in by_path.items():
                yield p, _strip_line_numbers('\n'.join(texts))
            continue
        headers = _header_slices(out)
        if headers:
            for p, text in headers.items():
                yield _norm_rel(p), _strip_line_numbers(text)
            continue
        shown = []
        for seg in _SEG_SPLIT.split(cmd):
            seg_files, _ = _segment_files(seg, cwd)
            shown.extend(seg_files)
        uniq = {_norm_rel(f) for f in shown}
        for _p in uniq:
            if _p:
                yield _p, _strip_line_numbers(out)

def test_answer_grounded():
    answer = _answer()
    paths, routines = _cited_paths(answer), _cited_routines(answer)
    assert paths or routines, 'the answer cites no file or routine'
    slices = list(_any_display_slices())
    opened = {p for p, _ in slices}
    for p in sorted(paths):
        assert any(_same_path(o, p) for o in opened), f'answer cites {p}, which was never displayed'
    for names, strict in sorted(routines):
        def shown(fn):
            rx = _def_regex(fn)
            lit = re.compile(r'[\'"]' + re.escape(fn) + r'[\'"]')
            loose = re.compile(r'(?<![\w$])' + re.escape(fn) + r'(?![\w$])')
            return any(rx.search(text) or lit.search(text)
                       or (not strict and loose.search(text))
                       for _p, text in slices)
        assert any(shown(fn) for fn in names), \
            f'answer cites {names[0]}, which was never displayed in any opened file'

_PATCH_MARKERS = ('diff --git', '--- ', '+++ ', '@@ ', 'old mode', 'new mode',
                  'new file mode', 'deleted file mode', 'rename from', 'rename to',
                  'copy from', 'copy to', 'similarity index', 'Binary files',
                  'GIT binary patch', 'index ')

def _patch_modifies_source():
    if _usable_row() is None:
        return None
    if 'git_patch' not in _result():
        return None
    p = _result().get('git_patch')
    if not isinstance(p, str):
        return None
    if not p.strip():
        return False
    for line in p.splitlines():
        if line.startswith(_PATCH_MARKERS):
            return True
        if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
            return True
    return None

def test_modified_code_penalty():
    assert _patch_modifies_source() is True
