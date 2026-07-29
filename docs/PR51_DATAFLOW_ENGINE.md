# PR51 — Interprocedural Data Flow Engine

PR51 adds a deterministic, provider-independent data-flow foundation for Atlas.

## Capabilities

- stable call graph construction;
- argument-to-parameter propagation;
- return-value propagation;
- intra-method assignment propagation;
- source-to-sink path reconstruction;
- recursion detection and configurable depth limits;
- immutable cached results;
- conversion to security finding traces;
- SARIF `codeFlows` generation from finding traces.

The engine consumes an explicit `DataFlowProgram`, keeping parsing concerns separate from flow analysis. Results are immutable and deterministic so repeated scans and CI baselines remain reproducible.
