# PR119 — IDE Assistant

PR119 provides one editor-neutral ASS protocol for VS Code, IntelliJ IDEA,
Visual Studio, Eclipse, and Neovim. Typed requests route Explain, Review, Ask,
and Fix to configured engines; semantic navigation is deterministic from ASS
symbols.

Requests identify an immutable snapshot and cannot carry raw source-code
fields. Host-specific extensions can remain thin transports over this API.
