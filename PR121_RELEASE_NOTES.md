# PR121 Release Notes

PR121 completes the production AI context path by replacing the default
workspace file counter with a semantic project analyzer.

The analyzer returns an immutable `SemanticDocument`, parses included Java
compilation units, creates global symbols, and reports parser diagnostics. The
context collector consumes these artifacts directly and retains its legacy
fallback for custom analyzers.

Semantic results now have a versioned, source-free persistence form for PR70
state and PR74 recovery. Deterministic report and history values preserve the
previous `project`, `files`, and `dependencies` summary.
