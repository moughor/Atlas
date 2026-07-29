# PR44 — Atlas Security Language Server

PR44 exposes Atlas Java security analysis through deterministic Language Server Protocol-style primitives.

## Capabilities

- initialize/shutdown lifecycle
- full-document open/change/save/close synchronization
- security diagnostics with zero-based LSP ranges
- severity, CWE, OWASP, confidence, and fingerprint metadata
- deterministic document and workspace symbols
- quick-fix command descriptors for suppress, explain, and rescan actions
- generic method dispatcher for embedding in stdio, socket, or editor adapters
- in-memory versioned document store

The core intentionally contains no transport dependency. A VS Code, IntelliJ, Neovim, or stdio adapter can serialize the returned dictionaries as JSON-RPC without coupling Atlas analysis to one editor.
