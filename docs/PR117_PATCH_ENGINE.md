# PR117 — Patch Engine

The Patch Engine asks a provider for a minimal unified diff grounded in ASS,
extracts only diff output, rejects absolute and traversal paths, and delegates
to Atlas validation. `GitPatchValidator` runs `git apply --check` without
modifying the worktree.

`atlas ai fix ROOT --objective TEXT` prints a validated proposal. It never
applies the patch.
