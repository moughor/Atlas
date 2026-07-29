# PR112 — Atlas AI CLI

PR112 adds the dedicated `atlas ai` namespace, separating deterministic Atlas
analysis commands from probabilistic reasoning:

```text
atlas ai context [ROOT]
atlas ai explain [ROOT]
atlas ai ask QUESTION [ROOT]
atlas ai review [ROOT]
atlas ai fix [ROOT]
```

`atlas ai context` is fully functional and reads `.atlas/ass/latest.ass` by
default. `--snapshot` selects a historical artifact and `--metadata` includes
the ASS envelope fields.

The explain, review, ask, and fix entry points validate that an ASS artifact is
available, then report that their dedicated roadmap engines are not yet
implemented. PR112 deliberately does not anticipate PR113–PR117 or invoke an
LLM without the corresponding validation and engine layers.
