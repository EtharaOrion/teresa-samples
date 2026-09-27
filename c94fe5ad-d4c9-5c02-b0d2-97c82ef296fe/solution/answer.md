# Ground Truth

Instance: `c94fe5ad-d4c9-5c02-b0d2-97c82ef296fe`
Repository: `swc-project/swc`
Base commit: `c55e52479765bf14c7d241efa70cca861d7699e5`
Family: `issue_localization`

All file paths, line numbers, and code excerpts below describe the production tree exactly as
it stands at `c55e52479765bf14c7d241efa70cca861d7699e5`.

---

## 1. The observable behaviour

A derived class written without its own constructor is lowered by swc into a plain function
whose body begins with a synthesized call to the superclass. When a runtime exception escapes
the superclass initializer, the JavaScript engine reports a stack frame for that synthesized
call. Consumers that resolve the emitted position mapping file back onto the original sources
find that this one frame carries no usable original position, so it collapses onto the start of
the file, while the frames produced by the surrounding generated code resolve correctly.

Every property of the report falls directly out of the production code:

- Two sources that look interchangeable behave differently because the trigger is whether the
  author wrote a constructor at all. A class that declares its own constructor is lowered from a
  parsed `Constructor` whose nodes carry real source positions, so every frame inside it
  resolves; a class that omits one is lowered from a manufactured `Constructor` whose nodes have
  none.
- One package that leans on decorators and another with none at all show the same defect,
  because several independent lowering passes each synthesize the missing constructor through
  one shared routine. Decorator lowering, field initializer lowering and plain class lowering
  all converge on it.
- A frame that starts resolving after an unrelated tidy up, with nobody able to reproduce the
  recovery on demand, is what it looks like from the outside when that tidy up happened to add
  an explicit constructor to the class in question.
- The generated JavaScript is correct and runs fine because the defect never touches the emitted
  program text. Only the mapping file is short an entry.
- Turning the minifier off changes nothing, because the position is already absent from the AST
  before any compression pass observes the node.
- Raising the configured output language level removes the symptom because the class lowering
  passes stop running at all, so no constructor is synthesized and no unpositioned node is
  created.

The frames immediately above and below the bad one resolve normally because those surrounding
nodes were parsed from real source and kept their positions; only the manufactured subtree is
unpositioned.

---

## 2. Root cause

**File:** `crates/swc_ecma_utils/src/lib.rs`
**Function:** `default_constructor` (line 2229)

This is the single routine in the tree that manufactures the missing constructor. At
`base_commit` it reads:

```rust
pub fn default_constructor(has_super: bool) -> Constructor {
    trace!(has_super = has_super, "Creating a default constructor");

    let span = DUMMY_SP;

    Constructor {
        span: DUMMY_SP,
        key: PropName::Ident("constructor".into()),
        is_optional: false,
        params: if has_super {
            vec![ParamOrTsParamProp::Param(Param {
                span,
                ...
            })]
        } else {
            Vec::new()
        },
        body: Some(BlockStmt {
            stmts: if has_super {
                vec![CallExpr {
                    span: DUMMY_SP,
                    callee: Callee::Super(Super { span: DUMMY_SP }),
                    args: vec![ExprOrSpread {
                        spread: Some(DUMMY_SP),
                        expr: Box::new(Expr::Ident(quote_ident!("args").into())),
                    }],
                    ..Default::default()
                }
                .into_stmt()]
            } else {
                Vec::new()
            },
            ..Default::default()
        }),
        ..Default::default()
    }
}
```

The decisive line is the `span: DUMMY_SP` on the `CallExpr` at line 2255. The routine takes a
single `bool` parameter and therefore has no positional information available to it at all.
Every node it produces, including the `super(...args)` call that the engine will later name in
a stack frame, is born with a dummy position. That dummy position is the state defect, and it
is created here and nowhere else.

Four properties of this routine matter to the diagnosis:

- **Nothing here is derived from parsed source.** Every node is built from scratch out of
  constants, so there is no position to inherit. The rest parameter built for the derived case
  takes the local `span` binding, which is itself `DUMMY_SP` (line 2240), and the `Super` callee
  inside the call carries a dummy span of its own (line 2256). The whole synthesized subtree is
  unpositioned, and the `CallExpr` is the node that surfaces as a stack frame.
- **The omission happens at creation time.** The position is never placed on the node and then
  removed later; it is absent from the moment the node exists. No pass downstream strips
  anything, which is why looking for the stage that "loses" the position leads nowhere.
- **This is the sole routine in the tree that manufactures this constructor.** Every lowering
  pass that needs one calls here rather than assembling its own, so there is exactly one place
  where the omission can be introduced and exactly one place where it can be corrected.
- **Six production call sites reach it**, enumerated in section 3, and each of them hands in a
  boolean and takes back a finished `Constructor` it had no opportunity to position.

---

## 3. Control flow into the root cause

Six production call sites reach `default_constructor`, spread over four crates. Each one owns
a different lowering strategy, and each one independently decides that the class it is
rewriting needs a constructor that the author did not write:

| Call site | Crate | Trigger |
|---|---|---|
| `crates/swc_ecma_compat_es2015/src/classes/constructor.rs:21`, inside `fold_constructor` | `swc_ecma_compat_es2015` | class syntax lowered to a function |
| `crates/swc_ecma_compat_es2022/src/class_properties/mod.rs:1026`, inside `process_constructor` | `swc_ecma_compat_es2022` | field initializers need a home |
| `crates/swc_ecma_compat_es2022/src/private_in_object.rs:177` | `swc_ecma_compat_es2022` | brand check installation |
| `crates/swc_ecma_transforms_compat/src/class_fields_use_set.rs:256` | `swc_ecma_transforms_compat` | field writes lowered to assignments |
| `crates/swc_ecma_transforms_proposal/src/decorator_impl.rs:333` | `swc_ecma_transforms_proposal` | decorator lowering |
| `crates/swc_ecma_transforms_proposal/src/decorators/mod.rs:319` | `swc_ecma_transforms_proposal` | legacy decorator lowering |

Every one of them calls the helper with a bare boolean and accepts whatever it returns. The
class node these passes are visiting does carry a real position in its own `Class::span`, but at
`base_commit` none of the six passes that value down into the helper, and the helper has no
parameter that could accept it. That is the cross-file relationship the diagnosis turns on: the
information needed to fix the defect is present at all six call sites and absent at the one
place that needs it.

The reason the reporter sees the same defect from packages using field initializers and from
packages using decorators is exactly this fan-in. Three unrelated feature areas converge on one
shared routine.

---

## 4. Data flow out to the visible symptom

Once the dummy position exists on the `CallExpr`, the rest of the pipeline behaves correctly and
still produces the broken artifact.

1. The synthesized `Constructor` is threaded through the owning pass, which appends the field
   initializers or decorator plumbing after the super call using
   `inject_after_super` (`crates/swc_ecma_utils/src/constructor.rs:9`). This routine only inserts
   the supplied statements after the existing super call and leaves positions untouched.
2. Code generation walks the resulting AST. `Emitter::emit_call_expr`
   (`crates/swc_ecma_codegen/src/lib.rs:994`) emits a mapping entry for every call expression
   through `srcmap!(node, true)` at line 999.
3. `srcmap!` (`crates/swc_ecma_codegen/src/macros.rs:108`) is where the dummy position is
   converted into silence:

   ```rust
   ($emitter:expr, $n:expr, true) => {{
       let lo = $n.span_lo();
       if !lo.is_dummy() {
           $emitter.wr.add_srcmap(lo)?;
       }
   }};
   ```

   Because `lo` is dummy for this one call expression, `add_srcmap` is never reached and no
   mapping entry is recorded for the generated `super(...args)` text.
4. `SourceMap::build_source_map_with_config`
   (`crates/swc_common/src/source_map.rs:1248`) applies a second dummy guard at line 1279 while
   turning collected positions into the emitted mapping file, so anything that slipped through
   as a dummy position is discarded there too.

The consumer therefore receives a mapping file in which the region of generated text covering
the synthesized super call has no entry of its own, and resolution falls back to the nearest
preceding entry, which is why the frame lands at the beginning of the file.

The whole chain is: `default_constructor` mints a dummy position, the owning lowering pass
accepts it, `emit_call_expr` asks `srcmap!` to record it, `srcmap!` discards dummy positions, and
the consumer resolves the frame to the wrong place.

---

## 5. The most tempting wrong location

**`fold_constructor` in `crates/swc_ecma_compat_es2015/src/classes/constructor.rs` (line 14).**

This is the location a shallow investigation stops at, and it is genuinely part of the flow:

```rust
pub(super) fn fold_constructor(
    constructor: Option<Constructor>,
    class_name: &Ident,
    class_super_name: &Option<Ident>,
    config: Config,
) -> FnDecl {
    let is_derived = class_super_name.is_some();
    let mut constructor = constructor.unwrap_or_else(|| default_constructor(is_derived));

    let is_constructor_default = constructor.span.is_dummy();
    if is_constructor_default {
        constructor.params.take();
    }
    ...
```

It attracts a wrong answer for four reasons. It is the routine that decides a constructor is
missing. It sits in the class lowering pass, which is the first place anyone searching for
"class" lands. It is reached directly from `Classes::class_to_stmts`
(`crates/swc_ecma_compat_es2015/src/classes/mod.rs:551`, function opening at line 501), which
already holds `class.span` and so looks like the natural owner of the position. And it visibly inspects a span on the very next
line.

It is innocent of the position loss for a precise reason: by the time control reaches line 24 the
`Constructor` value already exists and every node inside it already carries `DUMMY_SP`.
`fold_constructor` reads a span, it never assigns one to the super call, and it would behave
identically if the helper had supplied real positions. Its `unwrap_or_else` merely selects
between an author-written constructor and a synthesized one.

The span it inspects is a second, sharper trap. `constructor.span.is_dummy()` is the mechanism by
which this pass recognises that the constructor was injected rather than written, and it uses that
to drop the synthesized parameter list. An investigator who concludes that the remedy is to stamp
the class position onto the `Constructor` node itself would silently break that recognition, and
the parameters of every synthesized constructor would survive into the output. The dummy span on
the `Constructor` is load bearing; the dummy span on the inner `CallExpr` is the defect.

Two further plausible but innocent locations:

- `inject_after_super` (`crates/swc_ecma_utils/src/constructor.rs:9`) is the other shared routine
  every one of these passes calls, and it manipulates the same constructor body, but it only
  inserts the supplied statements after an existing super call, falling back to the head of the
  body when the constructor has none, and it leaves every existing position untouched.
- The `srcmap!` macro and `emit_call_expr` are where the missing entry becomes observable, but
  their dummy guard is correct behaviour for genuinely synthetic nodes. Treating the guard as the
  defect would suppress mappings correctness for every other injected node in the compiler.
- The parser is uninvolved. Every node it produces from real source carries a real position, which
  is precisely why an author written constructor resolves correctly and why the frames surrounding
  the injected one resolve correctly. The unpositioned subtree never passed through the parser at
  all; it was assembled from constants after parsing had finished.
- The consumer that reads the emitted mapping file behaves correctly too. It falls back to the
  nearest preceding entry because the entry it needs was never written, so the frame it reports is
  the honest consequence of an incomplete mapping file.

---

## 6. What the merged production change did

The upstream change threaded a real position from every call site into the shared helper, and
made the helper place that position on the inner super call alone.

In `crates/swc_ecma_utils/src/lib.rs` a span-taking variant was introduced and the original
signature was kept as a thin forwarding wrapper that supplies a dummy position:

```rust
pub fn default_constructor(has_super: bool) -> Constructor {
    default_constructor_with_span(has_super, DUMMY_SP)
}

pub fn default_constructor_with_span(has_super: bool, super_call_span: Span) -> Constructor {
    let super_call_span = super_call_span.with_hi(super_call_span.lo);
    Constructor {
        span: DUMMY_SP,
        ...
                vec![CallExpr {
                    span: super_call_span,
    ...
```

Three details carry the whole correction. The `Constructor` keeps `span: DUMMY_SP`, which
preserves the injected-constructor recognition described in section 5. The incoming span is
collapsed with `with_hi(super_call_span.lo)` into a zero width point at the start of the class, so
the synthesized call is attributed to the position just before the `class` keyword rather than
claiming the whole class body. And the synthesized parameter changed from the shared `span`
binding to an explicit `DUMMY_SP`, keeping the artificial parameter list unattributed.

Each of the six call sites was then updated to pass the class position it already had:

- `fold_constructor` gained a leading `class_span: Span` parameter, and
  `crates/swc_ecma_compat_es2015/src/classes/mod.rs` passes `class.span` into it.
- `process_constructor` in `crates/swc_ecma_compat_es2022/src/class_properties/mod.rs` gained a
  `class_span: Span` parameter, supplied from `class.span` by its caller.
- `crates/swc_ecma_compat_es2022/src/private_in_object.rs` passes the visited class node's `n.span`.
- `crates/swc_ecma_transforms_compat/src/class_fields_use_set.rs` replaced the `has_super: bool`
  field on `FieldsHandler` with `super_call_span: Option<Span>`, carrying the class span itself.
- `crates/swc_ecma_transforms_proposal/src/decorator_impl.rs` and
  `crates/swc_ecma_transforms_proposal/src/decorators/mod.rs` pass the decorated class node's span.

With a real position on the `CallExpr`, `srcmap!` takes its `add_srcmap` branch, the position
survives the dummy filter in `SourceMap::build_source_map_with_config`, and the emitted mapping
file gains an entry pointing at the class definition. The frame that previously collapsed onto
the first character of the file now resolves to the class the engine was actually constructing.

---

## 7. Why localisation requires reading several files

A correct diagnosis requires all of the following, none of which is visible from any single file:

- that the position is absent from the AST rather than dropped during emission, which requires
  reading `crates/swc_ecma_codegen/src/macros.rs` alongside `crates/swc_ecma_utils/src/lib.rs`;
- that the routine which mints the node accepts no position argument, which requires reading the
  helper signature;
- that the position needed is already available at the call sites as `Class::span`, which requires
  reading the calling passes;
- that the same helper is reached from field lowering, brand checks, and both decorator
  implementations, which explains why the reporter sees one defect across unrelated features and
  requires reading at least three crates;
- that the `Constructor` span is deliberately dummy and consumed as a signal downstream, which
  requires reading `fold_constructor` and understanding why it may keep its behaviour.

```json <!-- gold -->
{
  "file": "crates/swc_ecma_utils/src/lib.rs",
  "function": "default_constructor",
  "explanation": "default_constructor is the single shared routine that manufactures the constructor swc injects into a derived class that declares none. It accepts only a `has_super: bool` and therefore builds every node it returns with DUMMY_SP, including the `super(...args)` CallExpr at line 2255 whose generated text later appears as a runtime stack frame. Six production call sites across four crates reach it (fold_constructor in swc_ecma_compat_es2015/src/classes/constructor.rs, process_constructor in swc_ecma_compat_es2022/src/class_properties/mod.rs, private_in_object.rs, swc_ecma_transforms_compat/src/class_fields_use_set.rs, and both decorator passes in swc_ecma_transforms_proposal), each holding a real Class::span that it has no way to pass in. Downstream, Emitter::emit_call_expr invokes the srcmap! macro in swc_ecma_codegen/src/macros.rs, which records a mapping entry only when the low position is non-dummy, so the synthesized super call contributes no entry and consumers resolve that frame to the start of the file. fold_constructor is the most tempting wrong answer because it decides to inject the constructor and inspects a span on the following line, but it receives an already-built node and only reads constructor.span.is_dummy() to recognise an injected constructor and drop its parameters; that dummy Constructor span is deliberate, and the defect is the dummy span on the inner CallExpr."
}
```
