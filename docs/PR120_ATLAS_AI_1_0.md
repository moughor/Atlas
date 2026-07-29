# PR120 — Atlas AI 1.0

Atlas AI 1.0 integrates PR111–PR119 behind the stable `moughorai.ai` facade:

1. deterministic source analysis;
2. immutable Atlas Semantic Snapshot;
3. verified context and deterministic prompts;
4. provider abstraction (Ollama is the currently implemented provider);
5. Explain, Review, Ask, and non-applying Patch engines;
6. conversation memory, Git context, CLI, and IDE protocol.

`atlas ai version` reports version `1.0.0` and a machine-readable capability
manifest. The manifest intentionally does not claim OpenAI or Anthropic support.

The LLM reasons over verified semantic data. Atlas remains the owner of facts,
and patch proposals remain subject to deterministic validation.

`atlas analyze` now completes the runtime pipeline by collecting semantic
artifacts and publishing `.atlas/ass/latest.ass` after successful analysis.
