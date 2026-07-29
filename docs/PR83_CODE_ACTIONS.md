# PR83 LSP Code Actions

Atlas language servers advertise `codeActionProvider` and handle
`textDocument/codeAction` for open documents.

The default provider emits:

- `atlas.explainFinding` and `atlas.suppressFinding` quick fixes for each
  current diagnostic;
- `atlas.rescanDocument` as a source action.

Actions retain their originating diagnostics and carry deterministic command
arguments. LSP `context.only` filters exact kinds and their descendants.
Hosts can supply a custom `CodeActionProvider` to `AtlasLanguageServer`.

PR83 actions are commands only. Text-rewriting fixes are intentionally deferred
to the PR89 auto-fix framework.
