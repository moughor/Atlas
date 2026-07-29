from __future__ import annotations

import json
from dataclasses import asdict

from .analysis import ConstantPropagationAnalysis, DefUseAnalysis, LivenessAnalysis, ReachingDefinitionsAnalysis
from .cfg import ControlFlowGraph
from .models import ConstantKind, DataFlowReport, DataFlowStatistics, DeadAssignment


class DataFlowService:
    """Runs the PR37 intraprocedural data-flow analyses as one deterministic pipeline."""

    def analyze(self, cfg: ControlFlowGraph) -> DataFlowReport:
        reaching = ReachingDefinitionsAnalysis().analyze(cfg)
        liveness = LivenessAnalysis().analyze(cfg)
        chains = DefUseAnalysis().build(cfg, reaching)
        constants = ConstantPropagationAnalysis().analyze(cfg)
        live_map = {point.instruction: point for point in liveness}
        dead = tuple(
            DeadAssignment(instruction.id, instruction.defines, instruction.source_path, instruction.line)
            for instruction in cfg.instructions
            if instruction.defines
            and not instruction.side_effect
            and instruction.defines not in live_map[instruction.id].live_after
        )
        variables = set()
        for instruction in cfg.instructions:
            if instruction.defines:
                variables.add(instruction.defines)
            variables.update(instruction.uses)
        statistics = DataFlowStatistics(
            block_count=len(cfg.blocks), edge_count=len(cfg.edges), instruction_count=len(cfg.instructions),
            variable_count=len(variables), definition_count=len(chains), dead_assignment_count=len(dead),
        )
        warnings = tuple(f"unreachable block: {name}" for name in cfg.unreachable_blocks())
        return DataFlowReport(reaching, liveness, chains, constants, dead, statistics, warnings)

    def to_dict(self, report: DataFlowReport) -> dict[str, object]:
        def instruction_id(value):
            return value.qualified_name

        return {
            "schema_version": 1,
            "statistics": asdict(report.statistics),
            "warnings": list(report.warnings),
            "reaching_definitions": [
                {
                    "instruction": instruction_id(point.instruction),
                    "before": [f"{definition.variable}@{instruction_id(definition.instruction)}" for definition in sorted(point.before)],
                    "after": [f"{definition.variable}@{instruction_id(definition.instruction)}" for definition in sorted(point.after)],
                }
                for point in report.reaching_definitions
            ],
            "liveness": [
                {"instruction": instruction_id(point.instruction), "before": sorted(point.live_before), "after": sorted(point.live_after)}
                for point in report.liveness
            ],
            "def_use_chains": [
                {
                    "definition": f"{chain.definition.variable}@{instruction_id(chain.definition.instruction)}",
                    "uses": [instruction_id(use) for use in chain.uses],
                }
                for chain in report.def_use_chains
            ],
            "constants_before": [
                {
                    "instruction": instruction_id(point),
                    "values": {
                        variable: {"kind": value.kind.value, **({"value": value.value} if value.kind is ConstantKind.CONSTANT else {})}
                        for variable, value in values
                    },
                }
                for point, values in report.constants_before
            ],
            "dead_assignments": [
                {
                    "instruction": instruction_id(item.instruction), "variable": item.variable,
                    "source_path": item.source_path, "line": item.line, "reason": item.reason,
                }
                for item in report.dead_assignments
            ],
        }

    def to_json(self, report: DataFlowReport, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(report), indent=indent, sort_keys=True, default=str)
