# Task List

1. ✅ Locate class-lowering transform in swc source

2. ✅ Trace span propagation for constructor-related emitted frames

3. ✅ Identify the routine responsible for the DUMMY/0:0 span
fold_constructor - crates/swc_ecma_compat_es2015/src/classes/constructor.rs
4. ✅ Rule out innocent participants

5. ✅ Empirically confirm against checked-in .map fixture
5272/1 a.map: gen line 18 'function Foo() {' has no mapping at col 4; neighbours 17,19,20 mapped
6. ✅ Report findings, repo clean

