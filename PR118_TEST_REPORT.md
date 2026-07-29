# PR118 Test Report

Focused after handling unborn Git HEAD: `2 passed in 0.43s`.

Full: `3381 passed, 1 skipped in 8.05s`.

Clean replay on `c660635`: `3381 passed, 1 skipped in 8.17s`.

Two earlier replay attempts were invalid because pytest inherited the temporary
`GIT_INDEX_FILE`; they are not reported as passes.
