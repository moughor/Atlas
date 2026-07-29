# PR89 Auto-Fix Framework

Rules may optionally implement `fix(context, finding)` and return a `RuleFix`
containing sorted `SourceEdit` values. Edits use absolute character offsets and
may include `expected_text` to reject stale sources.

`AutoFixPlanner` associates findings with their owning rules, validates provider
results, attributes exceptions, and produces a stable `FixPlan`.

Applying a plan:

- excludes `review` fixes unless explicitly enabled;
- rejects missing, out-of-range, stale, duplicate, or overlapping edits;
- applies edits right-to-left per file;
- returns deterministic changed files and applied rule IDs.

`FileFixApplier` supports dry runs, confines all paths to a supplied root,
stages content in same-directory temporary files, and attempts rollback if a
replacement fails. Callers should still use version control before applying
large fix sets.
