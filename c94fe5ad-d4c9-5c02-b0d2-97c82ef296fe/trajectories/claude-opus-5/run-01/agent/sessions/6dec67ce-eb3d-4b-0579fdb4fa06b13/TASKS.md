# Task List

1. ✅ Locate class lowering (es2015 classes) transform in swc
crates/swc_ecma_compat_es2015/src/classes/{mod.rs,constructor.rs}
2. ✅ Trace how constructor frames get spans; find the span-losing producer
fold_constructor builds Function/FnDecl with ..Default::default() => DUMMY_SP; constructor.span read only for is_dummy()
3. ✅ Identify innocent participants vs culprit routine
srcmap! macro, JsWriter::srcmap, build_source_map_with_config, add_pure_comments/PURE, default_constructor, class_to_stmts DUMMY_SPs are all by-design
4. ✅ Explain file-dependence / flakiness / target bump
fold_class collapse branch (!has_super && cnt_of_non_directive==1) re-assigns function.span = class.span; target>=es2015 skips the pass
