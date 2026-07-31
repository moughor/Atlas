from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


@dataclass(frozen=True, slots=True)
class ExplainRequest:
    subject: str = "workspace"
    question: str = "Explain this workspace."
    conversation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExplainResult:
    markdown: str
    snapshot_id: str
    estimated_input_tokens: int
    conversation_id: int | None = None


class ExplainEngine:
    def __init__(
        self,
        client: LlmClient,
        *,
        prompt_builder: SemanticPromptBuilder | None = None,
        memory: ConversationMemoryStore | None = None,
    ) -> None:
        self.client = client
        self.prompts = prompt_builder or SemanticPromptBuilder()
        self.memory = memory

    def explain(self, snapshot: AtlasSemanticSnapshot, request: ExplainRequest | None = None) -> ExplainResult:
        selected = request or ExplainRequest()
        subject = selected.subject.strip()
        question = selected.question.strip()
        if not subject or not question:
            raise ValueError("explanation subject and question are required")
        repository_default = self._is_repository_default(selected)
        context = (
            self._repository_context(snapshot)
            if repository_default and snapshot.semantic_context.get("repository_summary")
            else snapshot.to_context()
        )
        prompt = self.prompts.build(
            question,
            context,
            template=(
                "atlas-repository-explanation-v1"
                if repository_default and snapshot.semantic_context.get("repository_summary")
                else "atlas-grounded-v1"
            ),
            variables={"subject": subject},
            model="",
        )
        conversation_id = selected.conversation_id
        if self.memory is not None:
            if conversation_id is None:
                conversation_id = self.memory.create(
                    snapshot.workspace_fingerprint,
                    title=f"Explain {subject}",
                ).id
            self.memory.append(
                conversation_id,
                ConversationRole.USER,
                question,
                references={"snapshot": snapshot.snapshot_id, "subject": subject},
            )
        response = self.client.complete(prompt.request)
        markdown = response.text.strip()
        if not markdown:
            raise ValueError("explanation provider returned empty output")
        if self.memory is not None and conversation_id is not None:
            self.memory.append(
                conversation_id,
                ConversationRole.ASSISTANT,
                markdown,
                references={"snapshot": snapshot.snapshot_id, "kind": "explanation"},
            )
        return ExplainResult(
            markdown,
            snapshot.snapshot_id,
            prompt.estimated_input_tokens,
            conversation_id,
        )

    @staticmethod
    def _is_repository_default(request: ExplainRequest) -> bool:
        return (
            request.subject.strip().casefold() in {"workspace", "repository"}
            and request.question.strip() == ExplainRequest().question
        )

    @staticmethod
    def _repository_context(snapshot: AtlasSemanticSnapshot) -> WorkspaceSemanticContext:
        source = snapshot.semantic_context
        summary = source.get("repository_summary")
        architecture = source.get("architecture", {})
        design_patterns = source.get("design_patterns")
        graph = source.get("semantic_graph", {})
        projects = summary.get("projects", ()) if isinstance(summary, Mapping) else ()
        findings = architecture.get("findings", ()) if isinstance(architecture, Mapping) else ()
        limitations = [
            "Context is source-free; no raw source code is included.",
            f"Detailed symbols omitted from this repository overview: {len(source.get('symbols', ()))} available.",
            f"Semantic graph summarized: {len(graph.get('nodes', ()))} nodes and {len(graph.get('edges', ()))} edges.",
        ]
        if not findings:
            limitations.append("No high-confidence architecture finding is available.")
        if isinstance(summary, Mapping) and not summary.get("framework_evidence"):
            limitations.append(
                "Framework scope evidence is unavailable in this snapshot; framework names are unscoped."
            )
        return WorkspaceSemanticContext({
            "schema_version": source.get("schema_version"),
            "workspace": {
                "root": source.get("workspace", {}).get("root"),
                "project_count": len(projects),
            },
            "repository_summary": ExplainEngine._compact_summary(summary),
            "architecture": ExplainEngine._compact_architecture(architecture),
            "design_patterns": ExplainEngine._compact_design_patterns(design_patterns),
            "limitations": limitations,
        })

    @staticmethod
    def _compact_summary(value: object) -> object:
        if not isinstance(value, Mapping):
            return {}
        declared = value.get(
            "declared_dependency_count_by_ecosystem",
            value.get("dependencies_by_ecosystem", {}),
        )
        framework_evidence = value.get("framework_evidence", ())
        return {
            key: value.get(key)
            for key in (
                "schema_version", "root", "projects", "languages",
                "build_systems",
                "entry_points", "module_hierarchy", "production_files",
                "test_files", "generated_files",
            )
        } | {
            "frameworks": ExplainEngine._framework_presentations(
                value.get("frameworks", ()),
                framework_evidence,
            ),
            "framework_evidence": framework_evidence,
            "declared_dependency_count_by_ecosystem": declared,
            "total_declared_dependency_records": value.get(
                "total_declared_dependencies",
                sum(declared.values()) if isinstance(declared, Mapping) else None,
            ),
            "dependency_manifest_count_by_ecosystem": value.get(
                "dependency_manifest_count_by_ecosystem",
            ),
            "total_dependency_manifests": value.get("total_dependency_manifests"),
        }

    @staticmethod
    def _compact_architecture(value: object) -> object:
        if not isinstance(value, Mapping):
            return {}
        ports = tuple(value.get("ports", ()))
        adapters = tuple(value.get("adapters", ()))
        infrastructure = tuple(value.get("infrastructure_layers", ()))
        return {
            "schema_version": value.get("schema_version"),
            "findings": value.get("findings", ()),
            "dependency_directions": value.get("dependency_directions", ()),
            "dependency_cycles": value.get("dependency_cycles", ()),
            "architectural_areas": value.get("bounded_contexts", ()),
            "ports": ports[:25],
            "port_count": len(ports),
            "adapters": adapters[:25],
            "adapter_count": len(adapters),
            "infrastructure_layers": infrastructure[:25],
            "infrastructure_layer_count": len(infrastructure),
            "dependency_analysis": value.get("dependency_analysis", {
                "executed": False,
                "evidence_edge_count": 0,
            }),
            "classification_conflicts": value.get("classification_conflicts", ()),
        }

    @staticmethod
    def _compact_design_patterns(value: object) -> object:
        if not isinstance(value, Mapping):
            return {
                "status": "unavailable",
                "findings": [],
                "limitations": [
                    "Structured design-pattern analysis is unavailable in this snapshot."
                ],
            }
        raw_findings = value.get("findings", ())
        findings = []
        if isinstance(raw_findings, (list, tuple)):
            for item in raw_findings:
                if not isinstance(item, Mapping):
                    continue
                participants = item.get("participants", ())
                evidence_ids = item.get("evidence_ids", ())
                findings.append({
                    "pattern": item.get("pattern"),
                    "status": item.get("confidence_tier", "unknown"),
                    "confidence": item.get("confidence"),
                    "participating_symbols_count": (
                        len(participants)
                        if isinstance(participants, (list, tuple))
                        else 0
                    ),
                    "evidence_count": (
                        len(evidence_ids)
                        if isinstance(evidence_ids, (list, tuple))
                        else 0
                    ),
                    "limitations": (
                        list(item.get("limitations", ()))
                        if isinstance(item.get("limitations", ()), (list, tuple))
                        else []
                    ),
                })
        findings.sort(key=lambda item: (
            str(item["pattern"]),
            str(item["status"]),
            float(item["confidence"] or 0.0),
            item["participating_symbols_count"],
            item["evidence_count"],
            tuple(map(str, item["limitations"])),
        ))
        limitations = []
        if not findings:
            limitations.append(
                "No evidence-backed design-pattern finding matched; this does not "
                "prove that the repository contains no design patterns."
            )
        return {
            "schema_version": value.get("schema_version"),
            "producer_version": value.get("producer_version"),
            "status": "available",
            "findings": findings,
            "limitations": limitations,
        }

    @staticmethod
    def _framework_presentations(
        frameworks: object,
        evidence: object,
    ) -> list[object]:
        if not isinstance(frameworks, (list, tuple)):
            return []
        records = tuple(evidence) if isinstance(evidence, (list, tuple)) else ()
        presentations: list[object] = []
        for framework in frameworks:
            related = [
                record for record in records
                if isinstance(record, Mapping)
                and record.get("framework") == framework
            ]
            scopes = sorted({
                str(record.get("scope"))
                for record in related
                if record.get("scope")
            })
            presentation: dict[str, object] = {"name": framework}
            if scopes:
                presentation["evidence_scopes"] = scopes
            if (
                str(framework).casefold().startswith("spring")
                and related
                and "project-local" not in scopes
            ):
                references = " ".join(
                    f"{record.get('project', '')} {record.get('reference', '')}"
                    for record in related
                ).casefold()
                if any(term in references for term in ("antora", "documentation", "docs")):
                    presentation["display_name"] = "Spring-related documentation tooling"
                else:
                    presentation["display_name"] = "Spring-related test or sample evidence"
                presentation["adoption"] = (
                    "Project-local evidence only; does not establish repository-wide "
                    "Spring Framework adoption."
                )
            presentations.append(presentation)
        return presentations
