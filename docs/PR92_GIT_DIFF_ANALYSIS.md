# PR92 Git Diff Analysis

Atlas can restrict findings to newly added Git lines:

```text
atlas check . --diff
atlas check . --staged
atlas check . --diff-base main --diff-head HEAD
```

`GitDiffService` invokes Git without a shell, validates revisions, and supports
working-tree, index, or two-commit comparison. `UnifiedDiffParser` produces
stable file/hunk models including added and removed lines, renames, additions,
deletions, and binary markers.

`GitDiffFilter` retains findings whose direct or nested location matches an
added line. Absolute paths may be normalized against a workspace root.
Analysis failures and non-finding run values remain unchanged. When baselines
and diffs are both enabled, PR77 baseline filtering occurs first.
