# PR139 Verification

## Baseline and roadmap compliance

PR139 was implemented from the exact pushed PR138 commit
`73cb441ac3637430d97c27904780b1c6cd12d96d` on `main`; `HEAD`, `origin/main`,
and `origin/HEAD` all identified that commit before implementation. The official
roadmap assigns **Interactive Engineering Chat** to PR139. PR139 therefore starts
that item and does not continue, complete, or broaden the deliberately partial PR138
Security Intelligence slice.

The implementation extends PR116 `AskEngine`, PR113
`ConversationMemoryStore`, and the established PR134 resolver and PR135 search
services. PR133 and PR136--PR138 remain optional findings providers. No second chat
engine, analyzer, graph, resolver, search index, evidence/confidence model, snapshot
store, conversation store, or cache was added. `ChatEngine`, `ChatRequest`, and
`ChatResult` are exact aliases of the existing Ask types.

## Focused and compatibility validation

The final focused command covered all six PR139 files:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr139_focused_final \
  tests/test_pr139_chat_cli.py \
  tests/test_pr139_chat_measurement.py \
  tests/test_pr139_chat_models.py \
  tests/test_pr139_conversation_turns.py \
  tests/test_pr139_interactive_chat.py \
  tests/test_pr139_optional_capabilities.py
```

Result: **92 passed in 3.53s**.

The compatibility matrix covered the frozen public API, semantic snapshots,
conversation memory, the legacy Ask Engine, subject resolution, structured
explanations, semantic search, impact prediction, refactoring advice, security
intelligence, and PR139. Result: **451 passed in 13.36s**.

The complete final command was:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr139_full_captured
```

Result: **4277 passed, 3 skipped in 38.37s**. The skips are the three existing
Windows symlink-capability tests. No warning was emitted by this run.

`python -m compileall -q moughorai tests` and `git diff --check` both exited 0.

## Determinism and adversarial coverage

Focused tests prove:

- reordered graph, symbol, project, evidence, capability, and section inputs produce
  identical canonical context JSON, digests, and prompts;
- Ask and Chat aliases produce identical canonical JSON envelopes;
- whole-section selection exposes exact total, included, and omitted counts;
- metadata declaring one included fact out of 1,000,000 remains a compact context
  without constructing a million-item input;
- unavailable, incompatible, stale, ambiguous, insufficient, and provider-failure
  states remain explicit and deterministic;
- citations are accepted only from the retained evidence closure;
- grounding requires compatible retained PR134/PR135 context and, for requested
  optional analysis, retained capability evidence;
- cross-workspace conversations, stale lineage, concurrent turn writers, malformed
  JSON, duplicate identities, unknown citations, unsafe provider text, credentials,
  absolute paths, private endpoints, and prompt-injection forms are rejected or
  redacted deterministically;
- existing conversation rows and context-free Ask results remain readable and
  ungrounded rather than being assigned fabricated lineage.

The controlled performance run executed nine identical requests in each zero-,
five-, and twenty-finding cohort. Every serialized result was byte-identical inside
its cohort. Detailed measurements are in `PR139_PERFORMANCE.md`.

## Snapshot and prior-feature compatibility

PR139 does not persist conversation data into semantic snapshots. A controlled
repository produced the exact same 138,998-byte ordinary snapshot under PR138 and
PR139, SHA-256
`0f0bedfeb886433ed72946da00cd77fcd2d87bf0a6101bad15b8d07ee00354fa`:
zero-byte, zero-percent growth.

PR137 refactoring output rendered from the same Maven snapshot remained exactly
2,677 bytes with SHA-256
`7d2aea37c39887efb8bf90db9ff7009fa47a406a78ecfad0704c0101c3e2763e`
under both revisions. PR138 focused compatibility and the complete suite passed.

The frozen public API remains version `1.0`: all 34 facade exports resolve, all 30
frozen signatures match, `public_api_compatibility_issues()` returns `()`, and the
canonical manifest SHA-256 is
`3c9fd367cb42101c75bc762255f56f45df605043d99f40f0df8cb41c068482bb`.
The three Chat aliases have exact type identity with their Ask counterparts, and
`AtlasAiCapabilities.engineering_chat` is appended after all legacy positional
fields.

## Source-free and security-language verification

The prompt and result boundaries admit only bounded structured semantic metadata.
They reject raw-source constructs, comments, literals classified as secrets,
credentials, absolute paths, private IPs, localhost, explicitly labelled private
host/server/endpoint values, and unsafe prior/provider text. Provider and model
metadata are sanitized before persistence. Dotted canonical semantic identifiers
remain available because syntax alone cannot distinguish a Java package from a host;
structured producers must label network metadata before projection.

Chat does not claim that zero findings prove security, executed rules prove complete
coverage, confidence proves exploitability, impact proves reachability, or severity
determines priority. Missing call, impact, refactoring, or security evidence remains
unavailable. The LLM cannot add evidence, alter confidence, resolve ambiguity, or
make a capability available.

## Clean replay

An alternate-index patch was checked and applied in a detached clean worktree at the
exact PR138 baseline `73cb441ac3637430d97c27904780b1c6cd12d96d`. It contained
exactly the 27 intended files. All 27 normalized file contents matched the main
candidate after application; Windows `core.autocrlf` accounted for raw newline
differences.

Replay validation results were:

- PR139 focused suite: **92 passed in 3.52s**;
- complete suite: **4277 passed, 3 skipped in 35.58s**;
- `python -m compileall -q moughorai tests`: exit 0;
- `git diff --check`: exit 0.

The final documentation-inclusive patch is separately apply-checked from the same
clean baseline. Its result is reported in the delivery handoff because recording
that check inside this document would itself change the checked bytes. No temporary
patch or replay worktree is retained.

## Official repository validation

Each official run used isolated Atlas state, preserved target tracked files, restored
the prior `.atlas` state, and verified that the 520-file production manifest remained
SHA-256
`798a71ae9d133b8557b2981709114a6e60a6a9167f461e2d93249a64f8f74d77`.

| Repository and pinned commit | Run 1 | Run 2 | Snapshot bytes | Deterministic evidence |
| --- | ---: | ---: | ---: | --- |
| Apache Maven `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92/92, 30.643s | 92/92, 30.346s | 33,806,488 | semantic/report/graph/security canonical hashes exact |
| Quarkus `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1442/1442, 404.127s | 1442/1442, 411.093s | 359,125,800 | raw ASS, snapshot ID, semantic/report/graph/security hashes exact |
| Spring Framework `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | 29/29, 103.624s | 29/29, 103.644s | 146,059,842 | semantic/report/graph/security canonical hashes exact |
| Elasticsearch `273e03a8a7149170fac16761af3fbf522b52f9fe` | 545/545, 581.337s | 545/545, 580.418s | 546,013,434 | semantic/report/graph/security canonical hashes exact |

Quarkus's exact repeated raw ASS SHA-256 was
`c6bfc4587876bbb6978fb80ac9a0a178774ecf82ffb378ed023e6e66ceb682aa`;
its snapshot ID was
`58347edefd723153acb866c388f3e1fd0bcb186d51d9d614c0684bb9089dbbec`.

| Repository | Semantic context | Repository report | Semantic graph | Security intelligence |
| --- | --- | --- | --- | --- |
| Maven | `eac346eb19dcdfb95e81d53448c97755c5a69765b109ee739bed914180adb273` | `c424e5245e1d20bd645da6c41067bc617c40bc2527d5a791a0540d3d8589f37f` | `b970094f08957515a397a66ab043afbc1614badebf775b5f15c7ed2260f50db7` | `6c19dd24586e1dd31abd51867d2606e06b4ed3af09b4cb6c85bd1118af2aae27` |
| Quarkus | `414fb780632d578f5de57998f4eaf6639f92177ba0fca414d5ed840d5965dc0f` | `a810c528ab3033d7450dc524cad036544518b8abbfe00bb6c67913c39a56a2e6` | `006fb4c5d91ca24c58f57f4b2a8e4d38fc6aee499a0a6f92101673a584ad91de` | `739928c8511de5e9774276280cec6a16bba28080bc02c98d4325319d11eb0b0f` |
| Spring | `c3180ed01470fa8552e189178e5496cc50e09c3611429c390a4b80e5e68b4db4` | `ba02987b29a45033f6c81aefb33293968ecef72b75c4070dafd991aac1543c40` | `a24feb3dfc43eae02ce5cf740671ccafa28e71a95ac12135dd1e3d5a95c69fa1` | `f96adfebad0dcf55d26500b7bf53aa069a783bb273733a95dd51acc54ec42524` |
| Elasticsearch | `ad0c18fe876861c0afb603f61a8cdd2c162d18d6f0fe909fd92a64faed24a3c6` | `16db65d6477446b76e71d2675a411ee6a38c68bd58fe24b4de26becd35971e0d` | `6dc9ca59b9bf5ecb981cbe8781709f9f4446640f0629d74b3ff58fdfb19fab9a` | `9a5c2786ddcab8cfee54abb6db5c999cb3b4dc3efa93de3c3ffcbd47aab55c4a` |

The two Maven raw envelopes differed only in lineage-bearing snapshot/history
identity because the validation intentionally advanced history between runs; their
canonical semantic context, repository report, graph, and security section were
exact. Their raw SHA-256 values were
`7b727731f28288e56c7bd91926f6e2cecc769a96e48a84905aed35287bc0e02c`
and `1949d8f819ff2a86fade70254809aa2b7efd8e368c53288b2e88f169551df8e3`;
snapshot IDs were
`3b21cf8f93f849a370763504f98c4f20286ea7254069e04eb43f323b623fdc62`
and `7bb8fb0524990190746025c9663ee2659a1557a6d4ba2779e5a5e5ae65b8117b`.
Spring's wrapper retained and compared those canonical artifacts but did not
retain the discarded fresh envelopes' raw hashes or snapshot IDs. Elasticsearch's
raw envelopes also differed while every requested canonical artifact and byte count
was exact; their SHA-256 values were
`7b5fa70ba43a93c2d062e35cbe1eaba87d233673b169bf7addb0c3de79cb0bfb`
and `7cfb783c88cb76487e9e65f99e4d1cd350d75eb8aa37c70a4e8624c407924752`.
Snapshot IDs and history references were not retained, so raw byte identity is not
claimed.

### IntelliJ accepted diagnostic

IntelliJ Community remained exactly **118/119** at pinned commit
`6affce35cb2aad82747b36e886836c44e0188e46`. Two fresh runs took 313.052s and
307.025s and reported the exact same sole failure:

```text
DuplicateTypeError: Duplicate Java type 'com.intellij.testFramework.TestDataFile' in project 'idea': C:\b137\idea\platform\testFramework\src\com\intellij\testFramework\TestDataFile.java and C:\b137\idea\plugins\kotlin\tests-common\test\com\intellij\testFramework\TestDataFile.java
```

Project order, status, failure/error, canonical report, stdout, and stderr were exact
across runs. Stdout was 41,705 bytes with SHA-256
`997798bdc6436818d21116aa419e15faa4179128a7011b7488f2ce312e60f0dc`;
stderr was 1,674 bytes with SHA-256
`b3f2488dc3e068ef41b3695dfc4e82df8f48d388beb44e83957acfaa04a4b6b7`.
Neither failed analysis published `latest.ass` or any `.ass` file. The accepted
project/module identity limitation is therefore visible and no invalid snapshot was
published.

## Delivery state

Suggested PR title:
`PR139 — Add deterministic evidence-grounded interactive engineering chat`

Suggested commit message:
`feat: add deterministic engineering chat`

The completed change contains 27 files: 14 modified and 13 added.

Modified:

- `CHANGELOG.md`
- `PR139_DESIGN.md`
- `README.md`
- `docs/PR113_CONVERSATION_MEMORY.md`
- `docs/PR116_ASK_ENGINE.md`
- `moughorai/ai/__init__.py`
- `moughorai/ai/capabilities.py`
- `moughorai/ai_ask/__init__.py`
- `moughorai/ai_ask/engine.py`
- `moughorai/ai_memory/__init__.py`
- `moughorai/ai_memory/models.py`
- `moughorai/ai_memory/store.py`
- `moughorai/atlas_cli.py`
- `moughorai/prompts/semantic.py`

Added:

- `docs/PR139_EXISTING_CAPABILITIES.md`
- `docs/PR139_INTERACTIVE_ENGINEERING_CHAT.md`
- `docs/PR139_PERFORMANCE.md`
- `docs/PR139_VERIFICATION.md`
- `moughorai/ai_ask/context.py`
- `moughorai/ai_ask/models.py`
- `moughorai/ai_ask/safety.py`
- `tests/test_pr139_chat_cli.py`
- `tests/test_pr139_chat_measurement.py`
- `tests/test_pr139_chat_models.py`
- `tests/test_pr139_conversation_turns.py`
- `tests/test_pr139_interactive_chat.py`
- `tests/test_pr139_optional_capabilities.py`

At handoff, `HEAD`, `origin/main`, and `origin/HEAD` remain the PR138 baseline;
nothing is staged, committed, or pushed. PR139-created benchmark state, `.atlas`
state, patches, ZIPs, replay worktrees, alternate indexes, test directories, and
generated validation artifacts are removed. Pre-existing ignored historical Atlas
state and earlier-PR artifacts are not represented as PR139 output and are preserved.

## Known limitations and deferred work

- Provider prose is nondeterministic and is never repository evidence.
- A valid citation proves membership in the retained bounded context, not semantic
  entailment of arbitrary provider prose.
- Ambiguous dotted text is retained when it is a valid canonical semantic identity;
  private network metadata requires producer-owned structured labeling.
- PR138 Security Intelligence remains the same deliberately partial first slice.
- Missing PR136 impact, PR137 advice, or PR138 security results are not recreated by
  chat.
- Autonomous tools, repository modification, multi-user/cross-repository memory,
  automatic fixes, and PR140 Git-aware review remain deferred.
