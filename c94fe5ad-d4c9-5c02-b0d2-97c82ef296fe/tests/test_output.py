from __future__ import annotations

import json
import os
import re

GOLDEN = {'answer': {},
 'negatives': [],
 'targets': [{'file': 'crates/swc_ecma_utils/src/lib.rs',
              'function': 'default_constructor',
              'weight': 5},
             {'file': 'crates/swc_ecma_codegen/src/macros.rs', 'function': 'srcmap', 'weight': 3},
             {'file': 'crates/swc_common/src/source_map.rs', 'function': None, 'weight': 1},
             {'file': 'crates/swc_ecma_codegen/src/lib.rs', 'function': None, 'weight': 1},
             {'file': 'crates/swc_ecma_compat_es2015/src/classes/constructor.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_compat_es2015/src/classes/mod.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_compat_es2022/src/class_properties/mod.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_compat_es2022/src/private_in_object.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_transforms_compat/src/class_fields_use_set.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_transforms_proposal/src/decorator_impl.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_transforms_proposal/src/decorators/mod.rs',
              'function': None,
              'weight': 1},
             {'file': 'crates/swc_ecma_utils/src/constructor.rs', 'function': None, 'weight': 1}],
 'symbols': [],
 'process_weights': {'answer_grounded': 1, 'read_only': 1, 'modified_code_penalty': -5}}

_JSONL_ENV = 'HG_OUTPUT_JSONL'

class RolloutError(RuntimeError):
    pass

def _no_dup(pairs):
    seen = {}
    for k, v in pairs:
        if k in seen:
            raise ValueError(f'duplicate key {k!r} in rollout JSON')
        seen[k] = v
    return seen

def _load_row() -> dict:
    path = os.environ.get(_JSONL_ENV)
    if not path:
        return {}
    if not os.path.exists(path):
        raise RolloutError(f'{_JSONL_ENV}={path} does not exist')
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = [line for line in fh if line.strip()]
        if not lines:
            raise RolloutError(f'{path} is empty')
        if len(lines) > 1:
            raise RolloutError(f'{path} holds {len(lines)} rows; exactly one is scored')
        row = json.loads(lines[0], object_pairs_hook=_no_dup)
    except OSError as exc:
        raise RolloutError(f'{path} could not be opened: {exc}') from exc
    except ValueError as exc:
        raise RolloutError(f'{path} is not valid JSONL: {exc}') from exc
    if not isinstance(row, dict):
        raise RolloutError(f'{path} row is {type(row).__name__}, not an object')
    return row

_ROW_CACHE = []

def _row() -> dict:
    if not _ROW_CACHE:
        _ROW_CACHE.append(_load_row())
    return _ROW_CACHE[0]

def _absent() -> str:
    return '' if _row() else f' (no rollout: {_JSONL_ENV} is unset)'

def _answer() -> str:
    a = (_row().get('test_result') or {}).get('answer')
    if isinstance(a, str):
        return a
    if isinstance(a, dict):
        return str(a.get('text') or '')
    return ''

def _patch():
    p = (_row().get('test_result') or {}).get('git_patch')
    return p if isinstance(p, str) else None

_SRC = r'\.(?:java|kt|go|rs|py|pyi|ts|tsx|js|jsx|mjs|rb|c|cc|cpp|h|hpp|scala|cs|swift|php|proto)'
_FILE = re.compile(r'[\w./+-]*?[\w+-]+' + _SRC + r'\b')
_DISPLAY = re.compile(r"\bsed\s+-n|\bawk\b[^|]*NR|\bcat\s|\bnl\b|\bhead\s|\btail\s"
                      r"|\bgrep\b[^|]*\s-[a-zA-Z]*n[a-zA-Z]*\b|\bless\b|\bbat\b"
                      r"|\bgit\s+show\s")
_SEARCH = re.compile(r'\b(?:grep|rg|ag|ack|git\s+grep)\b')
_LISTING = re.compile(r'^\s*(?:find|ls|git\s+ls-files|fd|tree|locate|stat)\b')
_ERROR_OUT = re.compile(r'^(?:[^\n]{0,60}?: )?(?:No such file or directory|command not found'
                        r'|Permission denied|cannot access|cannot open|Is a directory'
                        r'|unknown revision|Traceback \(most recent call last\))'
                        r'|^(?:fatal|error): ', re.I | re.M)

def _calls():
    hist = _row().get('history') or []
    obs = {e['cause']: str(e.get('content') or '') for e in hist
           if isinstance(e, dict) and e.get('observation') and e.get('cause') is not None}
    out = []
    for e in hist:
        if not (isinstance(e, dict) and e.get('source') == 'agent'):
            continue
        if e.get('action') == 'finish':
            break
        if e.get('action') not in ('run', 'read', 'edit'):
            continue
        a = e.get('args') or {}
        cmd = str(a.get('command') or '') if e['action'] == 'run' else str(a.get('path') or '')
        out.append((e['action'], cmd, obs.get(e.get('id'), '')))
    return out

def _norm_rel(p: str) -> str:
    p = p.replace('\\', '/').strip().strip('\'"')
    while p.startswith('./'):
        p = p[2:]
    return p.rstrip('/')

_VENDORED = re.compile(r'(?:^|/)(?:vendor|third_party|thirdparty|node_modules|\.venv|'
                       r'site-packages|external|Godeps)(?:/|$)')

def _names_path(text: str, path: str) -> bool:
    want = _norm_rel(path)
    want_vendored = _VENDORED.search(want) is not None
    for found in _FILE.findall(text):
        got = _norm_rel(found)
        if _VENDORED.search(got) and not want_vendored:
            continue
        if got == want or got.endswith('/' + want):
            return True
    return False

_SEP = re.compile(r'\|\||&&|[|;]')

def _strip_comment(seg: str) -> str:
    quote = ''
    for i, ch in enumerate(seg):
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '\'"':
            quote = ch
        elif ch == '#' and (i == 0 or seg[i - 1].isspace()):
            return seg[:i]
    return seg

def _segments(cmd: str):
    return [_strip_comment(s) for s in _SEP.split(cmd)]

def _display_segments(cmd: str):
    for seg in _segments(cmd):
        if _DISPLAY.search(seg) and not _LISTING.search(seg):
            yield seg

def _displays_of(path: str):
    for action, cmd, out in _calls():
        if not out.strip() or _ERROR_OUT.search(out):
            continue
        if action in ('read', 'edit'):
            if _names_path(cmd, path):
                yield out
            continue
        if any(_names_path(seg, path) for seg in _display_segments(cmd)):
            yield out

def _hit_lines_of(path: str):
    want = _norm_rel(path)
    for action, cmd, out in _calls():
        if action != 'run' or not out.strip() or _ERROR_OUT.search(out):
            continue
        if not any(_DISPLAY.search(seg) and not _LISTING.search(seg) for seg in _segments(cmd)):
            continue
        for line in out.splitlines():
            head = line.split(':', 1)[0] if ':' in line else ''
            if head and (_norm_rel(head) == want or _norm_rel(head).endswith('/' + want)):
                yield line

_PRE = r'^[ \t]*(?:(?:[^\n]*?[-:])?\d+[-:\t ])?[ \t]*'

def _definition_res(fn: str, owner: str):
    f = re.escape(fn)
    pats = [_PRE + r'(?:async[ \t]+)?def[ \t]+' + f + r'[ \t]*\(',
            _PRE + r'func[ \t]+' + f + r'[ \t]*[(\[]',
            _PRE + r'func[ \t]*\([^)\n]*\)[ \t]*' + f + r'[ \t]*[(\[]',
            _PRE + r'(?:pub[ \t]+)?(?:async[ \t]+)?fn[ \t]+' + f + r'[ \t]*[(<]',
            _PRE + r'(?:export[ \t]+)?(?:async[ \t]+)?function[ \t]+' + f + r'[ \t]*\(',
            _PRE + r'(?:(?:public|private|protected|static|final|abstract'
            r'|synchronized|default|native|strictfp)[ \t]+)*'
            r'[\w<>\[\],.?]+[ \t]+' + f + r'[ \t]*\(',
            _PRE + r'(?:pub[ \t]+)?(?:export[ \t]+)?'
            r'(?:struct|enum|trait|impl|type|class|interface)[ \t]+' + f + r'\b',
            _PRE + r'macro_rules![ \t]*!?[ \t]*' + f + r'\b']
    return [re.compile(p, re.M) for p in pats]

def _owner_res(fn: str, owner: str):
    f, o = re.escape(fn), re.escape(owner)
    return (re.compile(_PRE + r'func[ \t]*\([^)\n]*\b' + o + r'\b[^)\n]*\)[ \t]*' + f + r'[ \t]*[(\[]', re.M),
            re.compile(_PRE + r'(?:class|type|struct|impl|interface)[ \t]+' + o + r'\b', re.M))

def _stem(path: str) -> str:
    parts = [p for p in path.replace('\\', '/').rstrip('/').split('/') if p]
    base = parts[-1].rsplit('.', 1)[0]
    parent = parts[-2] if len(parts) > 1 else ''
    return re.sub(r'\W', '_', f'{parent}_{base}' if parent else base).strip('_')

_ANY_OWNER = re.compile(_PRE + r'(?:class|type|struct|impl|interface)[ \t]+(\w+)', re.M)
_GO_RECEIVER = re.compile(_PRE + r'func[ \t]*\([^)\n]*\)[ \t]*\w+[ \t]*[(\[]')

def _owner_owns_definition(out: str, defn, owner: str, recv, strict: bool = True) -> bool:
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if not any(p.search(line) for p in defn):
            continue
        if not owner:
            return True
        if recv is not None and recv.search(line):
            return True
        if _GO_RECEIVER.search(line):
            continue
        for j in range(i - 1, -1, -1):
            m = _ANY_OWNER.search(lines[j])
            if m:
                if m.group(1) == owner:
                    return True
                break
        else:
            if not strict:
                return True
    return False

def _definition_displayed(path: str, qualified: str, anchor: str = '') -> bool:
    fn = qualified.split('.')[-1]
    owner = qualified.split('.')[-2] if '.' in qualified else ''
    defn = _definition_res(fn, owner)
    recv, klass = _owner_res(fn, owner) if owner else (None, None)
    for out in _displays_of(path):
        if anchor and anchor not in out:
            continue
        if _owner_owns_definition(out, defn, owner, recv, strict=False):
            return True
    if anchor:
        return False
    for line in _hit_lines_of(path):
        if any(p.search(line) for p in defn) and (not owner or recv.search(line)):
            return True
    return False

def _make_target_test(t: dict):
    path = t['file']
    stem = _stem(path)
    qualified = (t.get('function') or '')
    anchor = t.get('anchor') or ''
    fn = qualified.split('.')[-1]
    if fn:
        def test():
            assert _definition_displayed(path, qualified, anchor), \
                (f'the definition of {qualified} was never displayed from {path}'
                 + (f' with {anchor!r} in the same output' if anchor else '') + _absent())
        test.__name__ = 'test_read_' + re.sub(r'\W', '_', fn) + '_in_' + stem
        test.__doc__ = f'The agent displayed the definition of {qualified or fn} in {path}.'
    else:
        def test():
            outs = [o for o in _displays_of(path) if not anchor or anchor in o]
            assert outs, (f'{path} was never displayed before finish'
                          + (f' with {anchor!r} in the output' if anchor else '') + _absent())
        test.__name__ = 'test_opened_' + stem
        test.__doc__ = (f'The agent displayed {path} (contents shown, not merely listed)'
                        + (f', including {anchor}.' if anchor else '.'))
    return test

for _t in GOLDEN.get('targets', []):
    _fn = _make_target_test(_t)
    globals()[_fn.__name__] = _fn

def _has_path_operand(seg: str) -> bool:
    for tok in seg.split():
        if tok.startswith('-'):
            continue
        tok = tok.strip('\'"')
        if tok in ('.', './') or '/' in tok or _FILE.search(tok):
            return True
    return False

def _search_segments(cmd: str):
    parts, seps = _SEP.split(cmd), _SEP.findall(cmd)
    for k, seg in enumerate(parts):
        if not _SEARCH.search(seg):
            continue
        if k and seps[k - 1] == '|' and not _has_path_operand(seg) \
                and _LISTING.search(parts[k - 1]) and not _DISPLAY.search(parts[k - 1]):
            continue
        yield seg

def _search_patterns():
    pats = []
    for action, cmd, _ in _calls():
        if action != 'run':
            continue
        for seg in _search_segments(cmd):
            pats += re.findall(r'["\']([^"\']{3,})["\']', seg)
            for tok in re.findall(r'(?<![\w/.\'"-])([A-Za-z_][\w.]{2,})(?![\w/])', seg):
                if tok in ('grep', 'rg', 'ag', 'ack', 'git', 'egrep', 'fgrep') or _FILE.fullmatch(tok):
                    continue
                pats.append(tok)
    return pats

def _make_symbol_test(sym: str):
    def test():
        assert any(sym in p for p in _search_patterns()), f'never searched for {sym}' + _absent()
    test.__name__ = 'test_searched_' + re.sub(r'\W', '_', sym)
    test.__doc__ = f'The agent searched the tree for {sym}.'
    return test

for _sym in GOLDEN.get('symbols', []):
    _fn = _make_symbol_test(_sym); globals()[_fn.__name__] = _fn

def _cited_paths(text: str):
    out = []
    for found in _FILE.findall(text):
        p = _norm_rel(found)
        if p and p not in out:
            out.append(p)
    return out

def _cited_targets(text: str):
    out = []
    for t in GOLDEN.get('targets', []):
        fn = (t.get('function') or '').split('.')[-1]
        if fn and re.search(r'\b' + re.escape(fn) + r'\b', text):
            out.append(t)
    return out

def _grounding_base_count(paths):
    known = {t['file'].replace('\\', '/').rstrip('/') for t in GOLDEN.get('targets', [])}
    known |= {p for p in paths if '/' in p}
    counts = {}
    for p in known:
        b = p.split('/')[-1]
        counts[b] = counts.get(b, 0) + 1
    return counts

def test_answer_grounded():
    ans = _answer()
    paths = _cited_paths(ans)
    targets = _cited_targets(ans)
    assert paths or targets, 'the answer cites no file and no routine' + _absent()

    counts = _grounding_base_count(paths)
    ungrounded = [p for p in paths if not any(True for _ in _displays_of(p))]
    assert not ungrounded, ('the answer cites ' + ', '.join(ungrounded)
                            + ' but their contents were never displayed' + _absent())

    unread = [f"{t['function']} in {t['file']}" for t in targets
              if not _definition_displayed(t['file'], t['function'])]
    assert not unread, ('the answer names ' + ', '.join(unread)
                        + ' but the definition was never displayed from that file' + _absent())

def _patch_modifies_source():
    p = _patch()
    if p is None:
        return None
    structured = False
    for line in p.splitlines():
        if line.startswith(('diff --git', 'rename ', 'new file', 'deleted file')):
            return True
        if line.startswith(('index ', '--- ', '+++ ', '@@')):
            structured = True
        elif line[:1] and line[0] in '+-':
            return True
    return False if structured or not p.strip() else None

def test_modified_code_penalty():
    assert _patch_modifies_source() is True
