# Task List

1. ✅ Locate the class-lowering transform and codegen sourcemap path

2. ✅ Trace how spans are assigned to the synthesized constructor / IIFE nodes
fold_constructor builds Function with ..Default::default() -> DUMMY_SP; FnDecl's #[span] delegates to function
3. ✅ Identify routine responsible and the innocent participants
Responsible: fold_constructor. Innocent: srcmap!, emit_fn_decl, JsWriter::add_srcmap/srcmap, build_source_map_with_config, fold_class, class_to_stmts, default_constructor, AST decls
4. ✅ Verify against committed fixture a.map
Decoded: line 18 'function Foo() {' mapped only at col 13 (ident); col 4 'function' unmapped. Control: method at line 25 IS mapped at its 'function' keyword col 19.
5. ✅ Write up explanation

