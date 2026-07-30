# PR110 — Ollama Integration

`OllamaProvider` implements the PR107 completion and streaming contract using
Ollama's local `/api/chat` endpoint. HTTP failures, timeouts, malformed JSON,
and invalid response shapes are normalized as `LlmProviderError`.

PR71 layered configuration is supported:

```yaml
llm:
  provider: ollama
  endpoint: http://localhost:11434
  model: my-coder:latest
```

Request-level model overrides take precedence over the configured model.
Temperature and output-token limits map to Ollama options. The provider owns
and closes only HTTP clients that it creates itself.
