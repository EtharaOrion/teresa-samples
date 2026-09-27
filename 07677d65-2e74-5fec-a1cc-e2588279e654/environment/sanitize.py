"""Line-preserving comment/docstring stripper for task workspaces.

Pre-existing comments and docstrings can leak the answer to comprehension
tasks, so runners strip them before the agent starts. Every edit preserves
the file's line count because gold labels and truth.md reference line
numbers in the original commit.

This module is staged into the sandbox verbatim and run with a bare `python3`
(see `maybe_sanitize_workspace`), so it must stay standard-library only.

Known limitations: JS template literals are consumed naively (until the next
unescaped backtick), so a nested backtick inside ${...} can misalign
stripping for the remainder of that file. C and C++ trigraphs are not decoded,
so the `??/` spelling of a line-splicing backslash is not recognised.
"""

import argparse
import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

# Every flag is declared once here, so a language line states only what it
# differs on and no config can be missing a key the scanner indexes.
_C_DEFAULTS = {
    'quotes': ('"',),
    'backtick': None,
    'char': False,
    'triple_double': False,
    'rust_raw': False,
    'nested_block': False,
    'cpp_raw': False,
    'line_continuation': False,
}

_C_FAMILY = {
    'js': {**_C_DEFAULTS, 'quotes': ('"', "'"), 'backtick': 'template'},
    'go': {**_C_DEFAULTS, 'backtick': 'raw', 'char': True},
    'java': {**_C_DEFAULTS, 'char': True, 'triple_double': True},
    'rust': {**_C_DEFAULTS, 'char': 'lifetime', 'rust_raw': True,
             'nested_block': True},
    # C and C++ differ only in raw string literals, which are C++11 and later.
    # Both splice a line ending in a backslash, so a // comment can run on.
    'c': {**_C_DEFAULTS, 'char': True, 'line_continuation': True},
    'cpp': {**_C_DEFAULTS, 'char': True, 'line_continuation': True,
            'cpp_raw': True},
}

EXTENSION_LANGS = {
    # .pyx/.pxd are Cython and .pyi is a stub, none of them strictly Python --
    # but this is a comment/docstring stripper, and the two forms that matter
    # (`#` comments and triple-quoted strings) are identical. `_strip_python`
    # already degrades to a line-based `#` strip when `tokenize` raises on
    # Cython-only syntax, and `sanitize_file` refuses to write when the line
    # count moves, so the worst case is a file left untouched rather than a
    # mangled one or a failed run. Cython matters here because in a scientific
    # Python repo the .pyx files hold the hot inner loops -- exactly where a
    # defect gets planted, and exactly what a comment gives away.
    '.py': 'python', '.pyx': 'python', '.pxd': 'python', '.pyi': 'python',
    '.js': 'js', '.jsx': 'js', '.mjs': 'js', '.cjs': 'js',
    '.ts': 'js', '.tsx': 'js', '.mts': 'js', '.cts': 'js',
    '.go': 'go',
    '.java': 'java',
    '.rs': 'rust',
    '.c': 'c',
    # `.h` is ambiguous, so it takes the superset. The raw-string scanner
    # validates before it consumes, so on a C header `R"x"` is left alone.
    '.h': 'cpp',
    '.cc': 'cpp', '.cpp': 'cpp', '.cxx': 'cpp', '.c++': 'cpp',
    '.hh': 'cpp', '.hpp': 'cpp', '.hxx': 'cpp', '.h++': 'cpp',
    '.inl': 'cpp', '.ipp': 'cpp', '.tcc': 'cpp', '.tpp': 'cpp',
    # `#`-comment formats. No docstrings and no block comments, so they need
    # only the line stripper below -- but they leak as readily as source does:
    # a repo's shell drivers and its YAML narrate the very machinery a
    # comprehension task asks the agent to derive.
    '.sh': 'hash', '.bash': 'hash', '.zsh': 'hash',
    '.yaml': 'hash', '.yml': 'hash',
    '.toml': 'hash', '.cfg': 'hash', '.ini': 'hash',
}

# Extensionless files whose LANGUAGE IS THEIR NAME. `_lang_from_shebang` cannot
# reach these -- a Dockerfile has no `#!` line and is not executable -- yet its
# comments describe the build the same way source comments describe the code.
FILENAME_LANGS = {
    'dockerfile': 'hash', 'makefile': 'hash', 'containerfile': 'hash',
    '.gitignore': 'hash', '.dockerignore': 'hash', '.env': 'hash',
}

# Markdown is deliberately absent from both maps. `#` opens a HEADING there, not
# a comment, so stripping those lines would gut the document rather than redact
# it -- and the prose in a checkout is often a deliberate decoy the instruction
# tells the agent to disregard ("go by the code"), so it is meant to survive.

_SKIP_DIRS = {'.git', '__pycache__', 'node_modules'}
_MAX_FILE_BYTES = 2_000_000

# Languages that must be selected together. `.h` maps to cpp, so filtering a C
# project to `c` alone would skip every one of its headers, and a C++ project
# routinely carries `.c` sources. Either name selects the pair.
_LANG_GROUPS = {'c': ('c', 'cpp'), 'cpp': ('c', 'cpp')}


def _spliced(text: str, newline: int) -> bool:
    """True when the line ending at `newline` ends with a backslash."""
    j = newline - 1
    if j >= 0 and text[j] == '\r':
        j -= 1
    return j >= 0 and text[j] == '\\'


# A raw string's R may only be preceded by one of these encoding prefixes.
_CPP_RAW_PREFIXES = ('', 'L', 'u', 'U', 'u8')
_CPP_RAW_MAX_DELIM = 16
_CPP_RAW_FORBIDDEN = ' \t\r\n()\\"'


def _cpp_raw_end(text: str, start: int) -> int | None:
    """End offset of the C++11 raw string literal at `start`, or None.

    Validates before consuming rather than assuming, which is what makes this
    safe to run over `.h`: in a C header `R"foo"` is a macro followed by an
    ordinary string, no `(` arrives before the closing quote, and the normal
    string path handles it instead.
    """
    # The R has to be a literal prefix, not the last letter of an identifier.
    j = start - 1
    while j >= 0 and (text[j].isalnum() or text[j] == '_'):
        j -= 1
    if text[j + 1 : start] not in _CPP_RAW_PREFIXES:
        return None
    n = len(text)
    delim_start = k = start + 2
    while k < n:
        if k - delim_start > _CPP_RAW_MAX_DELIM:
            return None
        ch = text[k]
        if ch == '(':
            closer = ')' + text[delim_start:k] + '"'
            end = text.find(closer, k + 1)
            return None if end == -1 else end + len(closer)
        if ch in _CPP_RAW_FORBIDDEN:
            return None
        k += 1
    return None


def _strip_c_family(text: str, cfg: dict) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ''
        if c == '/' and nxt == '/':
            while i < n and text[i] != '\n':
                i += 1
            # C and C++ splice a line ending in a backslash before comments are
            # removed, so the comment carries on. Without this the continuation
            # text survives as if it were code.
            while (
                cfg['line_continuation']
                and i < n
                and _spliced(text, i)
            ):
                out.append('\n')
                i += 1
                while i < n and text[i] != '\n':
                    i += 1
            continue
        if c == '/' and nxt == '*':
            depth = 1
            i += 2
            while i < n and depth:
                if cfg['nested_block'] and text[i] == '/' and i + 1 < n and text[i + 1] == '*':
                    depth += 1
                    i += 2
                    continue
                if text[i] == '*' and i + 1 < n and text[i + 1] == '/':
                    depth -= 1
                    i += 2
                    continue
                if text[i] == '\n':
                    out.append('\n')
                i += 1
            continue
        if cfg['triple_double'] and c == '"' and text[i:i + 3] == '"""':
            end = text.find('"""', i + 3)
            end = n if end == -1 else end + 3
            out.append(text[i:end])
            i = end
            continue
        if cfg['rust_raw'] and c == 'r' and nxt in ('"', '#'):
            j = i + 1
            hashes = 0
            while j < n and text[j] == '#':
                hashes += 1
                j += 1
            if j < n and text[j] == '"':
                closer = '"' + '#' * hashes
                end = text.find(closer, j + 1)
                end = n if end == -1 else end + len(closer)
                out.append(text[i:end])
                i = end
                continue
        if cfg['cpp_raw'] and c == 'R' and nxt == '"':
            end = _cpp_raw_end(text, i)
            if end is not None:
                out.append(text[i:end])
                i = end
                continue
        if c in cfg['quotes']:
            out.append(c)
            i += 1
            while i < n:
                ch = text[i]
                out.append(ch)
                i += 1
                if ch == '\\' and i < n:
                    out.append(text[i])
                    i += 1
                    continue
                if ch == c or ch == '\n':
                    break
            continue
        if c == '`' and cfg['backtick']:
            end = i + 1
            if cfg['backtick'] == 'raw':
                stop = text.find('`', end)
                end = n if stop == -1 else stop + 1
            else:
                while end < n:
                    if text[end] == '\\':
                        end += 2
                        continue
                    if text[end] == '`':
                        end += 1
                        break
                    end += 1
            out.append(text[i:end])
            i = end
            continue
        if c == "'" and cfg['char']:
            if cfg['char'] == 'lifetime' and nxt and (nxt.isalpha() or nxt == '_') \
                    and (i + 2 >= n or text[i + 2] != "'"):
                out.append(c)
                i += 1
                continue
            j = i + 1
            if j < n and text[j] == '\\':
                j += 2
                while j < n and text[j] != "'" and j - i < 12 and text[j] != '\n':
                    j += 1
            elif j < n:
                j += 1
            if j < n and text[j] == "'":
                out.append(text[i:j + 1])
                i = j + 1
                continue
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def _python_docstring_edits(text: str) -> list[tuple[int, int, int | None, str]]:
    edits: list[tuple[int, int, int | None, str]] = []
    tree = ast.parse(text)
    nodes = [tree] + [x for x in ast.walk(tree)
                      if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    for node in nodes:
        body = getattr(node, 'body', None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        val = body[0].value
        if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
            continue
        l0, c0 = val.lineno - 1, val.col_offset
        l1, c1 = val.end_lineno - 1, val.end_col_offset
        if l0 == l1:
            edits.append((l0, c0, c1, '""'))
        else:
            edits.append((l0, c0, None, '""'))
            for mid in range(l0 + 1, l1):
                edits.append((mid, 0, None, ''))
            edits.append((l1, 0, c1, ''))
    return edits


def _strip_python(text: str) -> str:
    try:
        edits = _python_docstring_edits(text)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                edits.append((tok.start[0] - 1, tok.start[1], None, ''))
    except (SyntaxError, ValueError, tokenize.TokenError):
        lines = text.split('\n')
        return '\n'.join('' if ln.lstrip().startswith('#') else ln for ln in lines)
    lines = text.split('\n')
    by_row: dict[int, list[tuple[int, int | None, str]]] = {}
    for row, start, stop, repl in edits:
        by_row.setdefault(row, []).append((start, stop, repl))
    for row, ops in by_row.items():
        line = lines[row]
        for start, stop, repl in sorted(ops, key=lambda o: o[0], reverse=True):
            tail = '' if stop is None else line[stop:]
            line = (line[:start] + repl + tail).rstrip() if repl == '' and stop is None \
                else line[:start] + repl + tail
        lines[row] = line
    return '\n'.join(lines)


_RUST_CFG_TEST = re.compile(r'#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]')
_RUST_MOD = re.compile(r'(?:pub\s*(?:\([^)]*\)\s*)?)?mod\s+\w+\s*')


def _rust_literal_end(text: str, i: int) -> int | None:
    """End offset just past a Rust string/char literal starting at i, else None.

    Handles raw/byte strings (r"..", br#".."#) and char literals so a brace or a
    quote inside them is never read as code. A lifetime ('a) returns None -- it
    carries no braces, so treating its ' as an ordinary char is safe.
    """
    n = len(text)
    c = text[i]
    if c in 'br':
        j = i + 1 if c == 'b' else i
        if j < n and text[j] == 'r':
            k = j + 1
            hashes = 0
            while k < n and text[k] == '#':
                hashes += 1
                k += 1
            if k < n and text[k] == '"':
                closer = '"' + '#' * hashes
                end = text.find(closer, k + 1)
                return n if end == -1 else end + len(closer)
    if c == '"' or (c == 'b' and i + 1 < n and text[i + 1] == '"'):
        j = i + (2 if c == 'b' else 1)
        while j < n:
            ch = text[j]
            if ch == '\\':
                j += 2
                continue
            if ch == '"':
                return j + 1
            j += 1
        return n
    if c == "'":
        j = i + 1
        if j < n and text[j] == '\\':
            j += 2
            while j < n and text[j] not in "'\n" and j - i < 16:
                j += 1
            return j + 1 if j < n and text[j] == "'" else None
        if i + 2 < n and text[i + 2] == "'":
            return i + 3
        return None
    return None


def _rust_match_brace(text: str, pos: int) -> int | None:
    """Index just past the '}' matching the '{' at pos, or None on imbalance.

    Skips string/char literals so a brace inside them never shifts the depth.
    """
    n = len(text)
    depth = 0
    i = pos
    while i < n:
        end = _rust_literal_end(text, i)
        if end is not None:
            i = end
            continue
        c = text[i]
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _strip_rust_cfg_test_blocks(text: str) -> str:
    """Remove `#[cfg(test)] mod NAME { ... }` blocks -- Rust's in-module unit
    tests, whose executable code (struct literals, assertions naming the exact
    fields) leaks a localization answer the same way a *_test file does.

    Line-count preserving: a removed block becomes as many blank lines as it
    spanned, so sanitize_file's newline invariant still holds. Only the dominant
    `mod` form is touched; a #[cfg(test)] on a use/fn, or cfg(all(test, ..)), is
    left intact. Fails safe: an unbalanced block is left untouched. The outer
    scan skips string literals, so an attribute inside a string is never matched.
    """
    n = len(text)
    out: list[str] = []
    i = 0
    while i < n:
        lit = _rust_literal_end(text, i)
        if lit is not None:
            out.append(text[i:lit])
            i = lit
            continue
        m = _RUST_CFG_TEST.match(text, i)
        if not m:
            out.append(text[i])
            i += 1
            continue
        j = m.end()
        while j < n and text[j] in ' \t\r\n':
            j += 1
        mod = _RUST_MOD.match(text, j)
        if not mod or mod.end() >= n or text[mod.end()] != '{':
            out.append(text[i:m.end()])
            i = m.end()
            continue
        close = _rust_match_brace(text, mod.end())
        if close is None:
            out.append(text[i:m.end()])
            i = m.end()
            continue
        out.append('\n' * text[i:close].count('\n'))
        i = close
    return ''.join(out)


def _strip_hash(text: str) -> str:
    """Blank `#` comments in shell/YAML while preserving every line.

    Deliberately conservative, because there is no tokenizer here and a wrong
    guess corrupts a file the agent then reads as truth:

    * A `#!` shebang on line 1 is kept. Removing it breaks the script, and it
      discloses nothing.
    * A whole-line comment is blanked outright -- that is the form that carries
      the narration worth hiding.
    * A trailing comment is removed ONLY when the code before it holds no quote
      character. `echo "a # b"` and `key: "a # b"` keep their `#`, because
      finding a real comment boundary there needs a parser this does not have.
      Leaving a trailing comment is a small leak; mangling a string literal is
      a broken checkout.
    """
    out = []
    for i, line in enumerate(text.split('\n')):
        stripped = line.lstrip()
        if i == 0 and stripped.startswith('#!'):
            out.append(line)
            continue
        if stripped.startswith('#'):
            out.append('')
            continue
        hash_at = line.find('#')
        if hash_at > 0 and '"' not in line[:hash_at] and "'" not in line[:hash_at]:
            out.append(line[:hash_at].rstrip())
            continue
        out.append(line)
    return '\n'.join(out)


def strip_comments(text: str, lang: str) -> str:
    if lang == 'python':
        return _strip_python(text)
    if lang == 'hash':
        return _strip_hash(text)
    cfg = _C_FAMILY.get(lang)
    if cfg is None:
        return text
    result = _strip_c_family(text, cfg)
    if lang == 'rust':
        result = _strip_rust_cfg_test_blocks(result)
    return result


# Comment and test stripping is line-count preserving so that line citations in
# the bundle stay valid while the strippers run -- but that leaves every removed
# comment block, docstring and #[cfg(test)] module behind as a run of blank
# lines. On the 250_top10 batch one file was 1,735 blank of 2,360 lines, and 9 of
# 10 agents noticed ("comments have been stripped ... probably intentionally for
# the task", "the injected bug", "benchmark artifact") and changed strategy. Once
# the strippers have finished and the newline invariant has been checked, squash
# those runs down to what ordinary source looks like. Line numbers below a
# collapsed run shift; the grader reconstructs the tree with this same code, so
# patches still apply, but bundle-side line citations refer to the upstream file.
_BLANK_RUN = re.compile(r'\n(?:[ \t\r]*\n){3,}')      # a line end + 3 or more blank lines
_LEADING_BLANKS = re.compile(r'\A(?:[ \t\r]*\n)+')     # blank lines before the first line of code
_TRAILING_BLANKS = re.compile(r'(?:[ \t\r]*\n){2,}\Z')  # blank lines after the last line of code
_WS_ONLY_LINE = re.compile(r'(?m)^[ \t]+$')            # an indented comment blanked to spaces
_KEEP_BLANK_LINES = 1


def _collapse_blank_runs(text: str, keep: int = _KEEP_BLANK_LINES) -> str:
    """Squash runs of 3+ blank lines to `keep`, drop leading blanks, and end
    the file with a single newline. Runs of 1-2 blank lines are ordinary
    formatting and are left alone."""
    text = _WS_ONLY_LINE.sub('', text)
    text = _LEADING_BLANKS.sub('', text)
    text = _BLANK_RUN.sub('\n' * (keep + 1), text)
    text = _TRAILING_BLANKS.sub('\n', text)
    return text


def sanitize_file(path: Path, lang: str) -> bool:
    raw = path.read_text(encoding='utf-8', errors='surrogateescape')
    stripped = strip_comments(raw, lang)
    # A `#!` line is not narration, and the Python stripper treats it as an
    # ordinary comment. Blanking it turns an executable driver into a file the
    # shell cannot run -- a behaviour change the agent would then be graded on.
    # `_strip_hash` already keeps it; this covers the python/shebang case that
    # `_lang_from_shebang` newly routes here.
    first = raw.split('\n', 1)[0]
    if first.startswith('#!'):
        tail = stripped.split('\n', 1)
        stripped = first + ('\n' + tail[1] if len(tail) > 1 else '')
    if stripped == raw:
        return False
    if stripped.count('\n') != raw.count('\n'):
        return False
    # Invariant checked above on the stripper's output; only now remove the
    # footprint. A shebang first line is unaffected (nothing precedes it).
    stripped = _collapse_blank_runs(stripped)
    path.write_text(stripped, encoding='utf-8', errors='surrogateescape')
    return True


def reset_git_repo(root: str | Path) -> bool:
    """Remove `.git` and reinitialize the repository with `git init`.

    The clone brings full upstream history along, so the agent's `git diff`
    would otherwise be measured against the pre-sanitize baseline and every
    stripped comment/docstring would show up as a change the agent did not
    make. Resetting to a fresh repo pins the baseline to the sanitized tree.

    Fails open: a missing git binary, an unwritable `.git`, or a failed init
    all return False rather than raise, so a sanitize call that succeeded on
    the source tree is never rolled back by a git-side problem.
    """
    root = Path(root)
    git_dir = root / '.git'
    if git_dir.exists():
        try:
            shutil.rmtree(git_dir)
        except OSError:
            return False
    try:
        subprocess.run(
            ['git', 'init', '.'],
            cwd=str(root),
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False
    return True


_SHEBANG_LANGS = (
    ('python', 'python'), ('bash', 'hash'), ('zsh', 'hash'), ('sh', 'hash'),
)


def _lang_from_shebang(path: Path) -> str | None:
    """Language for an extensionless file, read from its `#!` line.

    `path.suffix` is empty for `bin/pycbc_multi_inspiral` and every other
    extensionless driver, so the extension map alone skips them -- and those
    drivers are exactly the files a localization task asks the agent to trace.
    One real leak of 133 comment lines came from a single file of this shape.

    Only the first line is read, and only for files that are executable or live
    under a `bin/` directory, so this does not open every blob in the tree.
    """
    if path.suffix:
        return None
    if 'bin' not in path.parts and not os.access(path, os.X_OK):
        return None
    try:
        with path.open('r', encoding='utf-8', errors='surrogateescape') as fh:
            first = fh.readline(200)
    except OSError:
        return None
    if not first.startswith('#!'):
        return None
    for needle, lang in _SHEBANG_LANGS:
        if needle in first:
            return lang
    return None


def sanitize_workspace(
    root: str | Path,
    languages: list[str] | None = None,
    reset_git: bool = True,
) -> int:
    root = Path(root)
    wanted = set(languages) if languages else None
    if wanted:
        for lang in list(wanted):
            wanted.update(_LANG_GROUPS.get(lang, ()))
    changed = 0
    for path in root.rglob('*'):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        lang = EXTENSION_LANGS.get(path.suffix.lower())
        if lang is None:
            lang = FILENAME_LANGS.get(path.name.lower())
        if lang is None:
            lang = _lang_from_shebang(path)
        if lang is None or (wanted is not None and lang not in wanted):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            if sanitize_file(path, lang):
                changed += 1
        except Exception:
            continue
    if reset_git:
        reset_git_repo(root)
    return changed


# Test files ship the answer as executable code -- struct literals, assertions
# naming the exact fields -- that the comment stripper leaves intact, so on a
# localization/understanding task they hand the agent the solution (e.g.
# chainlock_test.go). Delete them by the language's test-file NAMING convention.
# Filename-based on purpose: it reliably catches the leak class without the false
# deletes a directory heuristic causes on repos that legitimately name a source
# dir 'test'. C/C++/Rust separate test files (*_test.cc, *_test.rs, cargo
# tests/ dir) are covered too; Rust's in-module #[cfg(test)] unit tests live
# inside the source file, so they are stripped in sanitize_file, not here.
_TEST_FILE_PATTERNS: dict[str, re.Pattern[str]] = {
    'python': re.compile(r'(?:^test_.+\.py$)|(?:_test\.py$)|(?:^conftest\.py$)', re.I),
    'go': re.compile(r'_test\.go$', re.I),
    'js': re.compile(r'\.(?:test|spec)\.(?:js|jsx|mjs|cjs|ts|tsx|mts|cts)$', re.I),
    # JUnit/Surefire/Failsafe: suffix (FooTest/Tests/TestCase/IT/ITCase) and
    # prefix (Test*/IT*). Case-sensitive -- Java test classes are capitalised, so
    # lowercasing would wrongly nuke files like 'manifest.java'.
    'java': re.compile(r'(?:^(?:Test|IT).+\.java$)|(?:(?:Test|Tests|TestCase|IT|ITCase)\.java$)'),
    # GoogleTest/common C++: foo_test.cc, foo_unittest.cpp, test_foo.cxx.
    'cpp': re.compile(r'(?:(?:_test|_tests|_unittest)\.(?:cc|cpp|cxx|c\+\+)$)|(?:^test_.+\.(?:cc|cpp|cxx|c\+\+)$)', re.I),
    # C: foo_test.c, test_foo.c.
    'c': re.compile(r'(?:_test\.c$)|(?:^test_.+\.c$)', re.I),
    # Rust separate test files; cargo integration tests (tests/ dir) are matched
    # by path in strip_test_files, and in-module #[cfg(test)] in sanitize_file.
    'rust': re.compile(r'_test\.rs$', re.I),
}


_TEST_DIR_NAMES = {'test', 'tests', '__tests__', 'spec', 'specs', 'testing'}

_TEST_CODE_MARKERS: dict[str, tuple[str, ...]] = {
    'python': ('def test_', 'class Test', 'import pytest', 'from pytest',
               'import unittest', 'from unittest', '@pytest.', 'self.assert'),
    'go': ('func Test', 'func Benchmark', 'func Fuzz', 'testing.T', 'testing.B'),
    'js': ('describe(', 'it(', 'test(', 'expect(', 'jest.', 'vitest'),
    'java': ('@Test', 'org.junit', 'Assert.', 'assertThat'),
    'rust': ('#[test]', '#[cfg(test)]', 'assert_eq!', 'assert!('),
}


def _in_test_dir(path: Path) -> bool:
    """True when some parent directory is conventionally a test directory."""
    return any(part.lower() in _TEST_DIR_NAMES for part in path.parts[:-1])


def _has_test_code(path: Path, lang: str) -> bool:
    """True when the file actually contains test code, not merely a test-ish name.

    Unreadable files, and languages with no marker list, are treated as tests:
    deleting a file we cannot inspect is the safe side of this trade, since
    leaving a real test in place would leak the answer.
    """
    markers = _TEST_CODE_MARKERS.get(lang)
    if not markers:
        return True
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return True
    return any(m in text for m in markers)


def strip_test_files(root: str | Path, languages: list[str] | None = None) -> int:
    """Delete repository test files whose executable code leaks the answer.

    Returns the count removed. Mirrors sanitize_workspace's traversal and its
    language filter; never raises on an individual file.
    """
    root = Path(root)
    wanted = set(languages) if languages else None
    if wanted:
        for lang in list(wanted):
            wanted.update(_LANG_GROUPS.get(lang, ()))
    removed = 0
    for path in root.rglob('*'):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        lang = EXTENSION_LANGS.get(path.suffix.lower())
        if lang is None or (wanted is not None and lang not in wanted):
            continue
        pattern = _TEST_FILE_PATTERNS.get(lang)
        is_test = pattern is not None and pattern.search(path.name) is not None
        # Cargo integration tests are ordinary-named .rs files under a tests/ dir.
        if lang == 'rust' and not is_test and 'tests' in path.parts:
            is_test = True
        if not is_test:
            continue
        # A NAME match is not proof. `bugbug/test_scheduling.py` is a production
        # module whose name happens to start with test_; deleting it removed the
        # gold file for instance cd13a965 and made that task unsolvable -- the
        # agent searched for code that was never in the container. Outside a
        # tests/ directory, require actual test CODE before deleting. The check
        # reads only the file itself, so nothing about the gold leaks inward.
        if not _in_test_dir(path) and not _has_test_code(path, lang):
            continue
        try:
            path.unlink()
            removed += 1
        except Exception:
            continue
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--languages', default='',
                        help='comma-separated subset of: python,js,go,java,rust,c,cpp')
    parser.add_argument('--strip-tests', action='store_true',
                        help='also delete test files whose executable code leaks the answer')
    parser.add_argument('--no-reset-git', dest='reset_git', action='store_false',
                        help='keep the cloned .git dir (default: rm -rf .git && git init .)')
    parser.set_defaults(reset_git=True)
    args = parser.parse_args()
    langs = [x.strip() for x in args.languages.split(',') if x.strip()] or None
    # --languages narrows the TEST-STRIPPING pass only, never the comment sweep.
    #
    # The caller derives it from the bundle's single declared `language`, which
    # says where the answer lives -- not where comments can leak. Real checkouts
    # are polyglot: a Go repo carries YAML and shell, a Python repo carries
    # Cython and driver scripts, and every one of those files keeps its comments
    # if the sweep is filtered. Passing None here sweeps every language the
    # stripper knows, which is strictly more coverage using machinery that is
    # already there.
    #
    # Test stripping keeps the filter because it DELETES files rather than
    # rewriting them, and its filename patterns are language-specific; widening
    # that is a separate decision with a much larger blast radius.
    changed = sanitize_workspace(args.root, None, reset_git=args.reset_git)
    print(f'sanitized {changed} files under {args.root}')
    if args.strip_tests:
        removed = strip_test_files(args.root, langs)
        print(f'stripped {removed} test files under {args.root}')
    if args.reset_git:
        print(f'reset git repo at {args.root}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
