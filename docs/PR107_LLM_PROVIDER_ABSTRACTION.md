# PR107 — LLM Provider Abstraction

`moughorai.llm` defines provider-neutral immutable requests, responses, stream
chunks, a runtime-checkable provider protocol, a thread-safe registry, and a
retrying client with explicit timeout propagation.

Streaming retries are allowed only before the first chunk. Once output has been
emitted, an interrupted stream fails rather than duplicating content.

PR107 performs no network I/O and registers no provider by default. Concrete
providers begin with PR110.
