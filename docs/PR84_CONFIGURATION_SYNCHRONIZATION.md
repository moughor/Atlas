# PR84 Configuration Synchronization

The workspace language server advertises workspace configuration support and
handles `workspace/didChangeConfiguration`, `workspace/configuration`, and
`workspace/didChangeWatchedFiles`.

Client settings may be nested beneath `atlas`. They are flattened into PR71
override keys and take precedence over workspace and project options.
Configuration generations increase after successful client updates or
`atlas.yaml` reloads.

Open documents are reanalyzed after synchronization. Resulting
`textDocument/publishDiagnostics` messages are available in deterministic URI
order through `drain_notifications()`.

Watched configuration reload is transactional: Atlas constructs a replacement
workspace service first, and retains the previous service and generation when
discovery or parsing fails.
