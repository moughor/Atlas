# PR90 Rule Pack Builder

`RulePackBuilder` combines a `RulePackSpec`, PR88 rule metadata, explicit Python
entry points, and source files into a reproducible ZIP archive.

The canonical `manifest.json` includes schema, pack/API semantic versions,
dependencies, full rule metadata, entry points, and size/SHA-256 records for
every file. Archive paths must be relative and traversal-free, and entry-point
modules must be present.

Build output is reproducible: entries are sorted, timestamps are fixed to the
ZIP epoch, permissions are normalized, JSON is canonical, and compression
settings are fixed.

`RulePackReader.verify` rejects invalid archives, unsupported schemas,
duplicate/unsafe/undeclared/missing files, and size or checksum mismatches.
