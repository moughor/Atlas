# PR37 — Data Flow Analysis

PR37 introduces `moughorai.data_flow`, an immutable intraprocedural data-flow framework built around an explicit control-flow graph (CFG).

## Scope

- Validated basic blocks, instructions, and typed control-flow edges
- Deterministic reachability and reverse-postorder traversal
- Reaching definitions with kill/gen semantics
- Backward live-variable analysis
- Definition-use chain construction
- Constant propagation over branch joins and loops
- Dead-assignment diagnostics that preserve side effects
- Unreachable-block warnings, statistics, and versioned JSON export

The IR is deliberately language-neutral. Java semantic passes can populate it without coupling the solvers to a particular parser or AST implementation.

## Example

```python
from moughorai.data_flow import BasicBlock, ControlFlowGraph, DataFlowService, Instruction

cfg = ControlFlowGraph([
    BasicBlock("entry", (
        Instruction.assign("entry", 0, "x", constant=1, has_constant=True),
        Instruction.assign("entry", 1, "y", uses=("x",)),
    )),
])

report = DataFlowService().analyze(cfg)
print(report.statistics)
```

## Design guarantees

- Immutable public model objects
- Stable instruction identities (`block:index`)
- Deterministic ordering and serialization
- Fixed-point convergence for cyclic CFGs
- No suppression of side-effecting assignments
- Independent analyses exposed individually and through `DataFlowService`
