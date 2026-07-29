# PR41 — Path-Sensitive Symbolic Execution

PR41 adds a bounded symbolic executor over Atlas's PR37 control-flow graph.

## Capabilities

- immutable symbolic values and states
- constant, variable, unary, and binary expressions
- equality, inequality, ordering, and null constraints
- true/false branch forking
- infeasible-path pruning
- deterministic state merging
- configurable global, depth, and per-block limits
- symbolic assignment propagation
- assertion proof, violation, and unknown outcomes
- unreachable-instruction reporting
- terminal-state collection
- security-finding reachability refinement

## Instruction metadata

Branch and assertion instructions use deterministic metadata entries:

- `operator`: `==`, `!=`, `<`, `<=`, `>`, or `>=`
- `left`: optional left operand; defaults to the first used variable
- `right`: optional literal or variable; defaults to `true`
- `assert=true`: evaluate the instruction as an assertion

Binary assignments use `operator` together with the first two variables in `uses`.

## Safety limits

`ExecutionOptions` bounds total explored states, path depth, and states retained per block. Reaching a limit produces a warning rather than non-deterministic behavior.
