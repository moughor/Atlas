from __future__ import annotations

from pathlib import Path

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_explain import ExplainEngine
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.repository_summary import RepositorySummaryService
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import WorkspaceService


def _snapshot(context: dict[str, object]) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="workspace",
        analyzer_version="test",
    )


def test_default_report_does_not_accept_provider_fact_substitution() -> None:
    snapshot = _snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{
                "name": "root",
                "path": ".",
                "files": 12_889,
                "size": 127_490_025,
                "build_systems": ["Maven", "Gradle"],
            }],
            "languages": {"Java": 22_166, "JavaScript": 2_053},
            "build_systems": ["Gradle", "Maven"],
            "production_files": 12_889,
        },
    })
    provider = ScriptedLlmProvider([
        "production_files=1, frameworks=Spring Boot, entry=Invented.java"
    ])

    result = ExplainEngine(LlmClient(provider)).explain(snapshot)

    assert provider.calls == []
    assert "12,889" in result.markdown
    assert "Spring Boot" not in result.markdown
    assert "Invented.java" not in result.markdown
    assert result.estimated_input_tokens == 0


def test_legacy_snapshot_without_repository_summary_reports_unknown_not_zero() -> None:
    snapshot = _snapshot({"workspace": {"root": "C:/legacy"}})
    provider = ScriptedLlmProvider(["Invented legacy facts"])

    result = ExplainEngine(LlmClient(provider)).explain(snapshot)
    context = ExplainEngine._repository_context(snapshot).to_dict()

    assert provider.calls == []
    assert context["workspace"]["discovered_project_count"] is None
    assert context["workspace"]["evidence_basis"] is None
    assert context["repository_summary"]["status"] == "unavailable"
    assert "Discovered projects | Unavailable" in result.markdown
    assert "Detailed symbol count is unavailable" in result.markdown
    assert "Invented legacy facts" not in result.markdown


def test_project_count_reports_the_exact_source_used() -> None:
    explicit = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo", "projects": [{"name": "fallback"}]},
        "repository_summary": {
            "root": "C:/demo",
            "project_count": 7,
            "projects": [{"name": "summary"}],
        },
    })).to_dict()["workspace"]
    legacy = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "one"}, {"name": "two"}],
        },
    })).to_dict()["workspace"]
    workspace_fallback = ExplainEngine._repository_context(_snapshot({
        "workspace": {
            "root": "C:/demo",
            "projects": [{"name": "one"}, {"name": "two"}, {"name": "three"}],
        },
    })).to_dict()["workspace"]

    assert (explicit["discovered_project_count"], explicit["evidence_basis"]) == (
        7, "repository_summary.project_count",
    )
    assert (legacy["discovered_project_count"], legacy["evidence_basis"]) == (
        2, "repository_summary.projects",
    )
    assert (
        workspace_fallback["discovered_project_count"],
        workspace_fallback["evidence_basis"],
    ) == (3, "workspace.projects")


def test_language_distribution_is_exact_reproducible_and_retains_tiny_languages() -> None:
    summary = {
        "root": "C:/demo",
        "projects": [{"name": "root", "path": "."}],
        "languages": {"Zulu": 1, "Alpha": 1, "Tiny": 1, "Dominant": 100_000},
    }
    first = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": summary,
    })).to_dict()["repository_summary"]["language_distribution"]
    reordered = {
        **summary,
        "languages": dict(reversed(tuple(summary["languages"].items()))),
    }
    second = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": reordered,
    })).to_dict()["repository_summary"]["language_distribution"]

    assert first == second
    assert first["percentage_total_basis_points"] == 10_000
    assert sum(item["basis_points"] for item in first["items"]) == 10_000
    assert next(item for item in first["items"] if item["language"] == "Tiny")["file_count"] == 1


def test_build_systems_use_counts_and_roles_not_overlapping_percentages() -> None:
    context = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [
                {"name": "root", "path": ".", "build_systems": ["Maven"]},
                {"name": "fixture", "path": "fixture", "build_systems": ["Gradle", "Maven"]},
            ],
            "build_systems": ["Gradle", "Maven"],
        },
    })).to_dict()
    builds = context["repository_summary"]["build_systems"]
    by_name = {item["name"]: item for item in builds["items"]}

    assert builds["percentages_reported"] is False
    assert by_name["Maven"]["detected_project_count"] == 2
    assert by_name["Maven"]["classification"] == "detected-in-root-project-inventory"
    assert by_name["Gradle"]["detected_project_count"] == 1
    assert by_name["Gradle"]["classification"] == "detected-in-projects"


def test_entry_candidates_do_not_gain_runtime_roles_from_names() -> None:
    context = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "demo", "path": "."}],
            "entry_points": [
                "demo:src/main/java/demo/Main.java",
                "demo:src/test/java/demo/GeneratedResourceBuildItem.java",
                "demo:target/generated-test-sources/demo/GeneratedMain.java",
            ],
        },
    })).to_dict()
    entries = context["repository_summary"]["entry_point_candidates"]

    assert entries["resolved_role_categories"] == []
    assert all(item["runtime_role"] == "unknown" for item in entries["items"])
    build_item = next(item for item in entries["items"] if "BuildItem" in item["path"])
    assert build_item["scope_candidate"] == "test-candidate"
    generated = next(item for item in entries["items"] if "GeneratedMain" in item["path"])
    assert generated["scope_candidate"] == "generated-candidate"
    assert "build-pipeline" in entries["unavailable_role_categories"]


def test_name_only_architecture_evidence_remains_insufficient() -> None:
    context = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [{"name": "service-one", "path": "."}],
        },
        "architecture": {
            "findings": [{
                "architecture": "microservices",
                "confidence": 0.8,
                "evidence": [{
                    "kind": "project-entry-point",
                    "reference": "service-one",
                    "detail": "Main.java",
                }],
            }, {
                "architecture": "invented-forward-pattern",
                "confidence": 0.99,
                "evidence": [{
                    "kind": "guess",
                    "reference": "unknown",
                    "detail": "unsupported future evidence kind",
                }],
            }],
            "dependency_analysis": {"executed": False, "evidence_edge_count": 0},
        },
    })).to_dict()
    architecture = context["architecture"]

    assert all(item["status"] == "insufficient" for item in architecture["findings"])
    microservices = next(
        item for item in architecture["findings"]
        if item["architecture"] == "microservices"
    )
    assert microservices["producer_confidence"] == 0.8
    assert architecture["dependency_analysis"]["status"] == "unavailable"
    assert architecture["dependency_analysis"]["cycle_count"] is None


def test_invalid_confidence_values_never_become_positive_conclusions() -> None:
    invalid_scores = [float("nan"), float("inf"), -0.01, 1.01]
    context = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {"root": "C:/demo", "projects": []},
        "architecture": {
            "findings": [
                {
                    "architecture": f"invalid-{index}",
                    "confidence": score,
                    "evidence": [{
                        "kind": "architecture-contract",
                        "reference": f"contract-{index}",
                    }],
                }
                for index, score in enumerate(invalid_scores)
            ],
        },
        "design_patterns": {
            "findings": [{
                "pattern": "invalid",
                "confidence": float("nan"),
                "confidence_tier": "high",
            }],
        },
        "reachability": {
            "coverage": {"status": "partial", "projects": []},
            "statistics": {"states": {}},
            "findings": [{
                "subject_id": "method:invalid",
                "state": "likely_dead",
                "confidence": float("inf"),
                "confidence_tier": "high",
            }],
        },
    })).to_dict()

    assert all(
        item["producer_confidence"] is None and item["status"] == "insufficient"
        for item in context["architecture"]["findings"]
    )
    assert context["design_patterns"]["pattern_types"][0]["status_counts"] == {
        "insufficient": 1,
    }
    reachability = context["reachability"]["representative_findings"][0]
    assert reachability["confidence"] is None
    assert reachability["confidence_tier"] == "insufficient"


def test_architecture_relationship_projection_ignores_input_order() -> None:
    architecture = {
        "findings": [],
        "dependency_analysis": {"executed": True, "evidence_edge_count": 2},
        "dependency_directions": [
            {"source": "z", "target": "a"},
            {"source": "a", "target": "z"},
        ],
        "dependency_cycles": [["z", "a"], ["a", "z"]],
    }
    base = {
        "workspace": {"root": "C:/demo"},
        "repository_summary": {"root": "C:/demo", "projects": []},
    }
    first = ExplainEngine._repository_context(_snapshot({
        **base, "architecture": architecture,
    })).to_dict()["architecture"]
    second = ExplainEngine._repository_context(_snapshot({
        **base,
        "architecture": {
            **architecture,
            "dependency_directions": list(reversed(architecture["dependency_directions"])),
            "dependency_cycles": list(reversed(architecture["dependency_cycles"])),
        },
    })).to_dict()["architecture"]

    assert first == second


def test_grouped_reachability_retains_exact_candidate_and_omitted_counts() -> None:
    subject_ids = [f"item-{index:03d}" for index in range(100)]
    source = {
        "workspace": {"root": "C:/demo"},
        "repository_summary": {"root": "C:/demo", "projects": []},
        "reachability": {
            "coverage": {"status": "partial", "projects": []},
            "statistics": {"analyzed_symbols": 100, "states": {"likely_dead": 100}},
            "finding_groups": [{
                "state": "likely_dead",
                "confidence": 0.8,
                "confidence_tier": "high",
                "subject_id_prefix": "method:",
                "subject_ids": subject_ids,
                "evidence_ids": ["z:evidence", "a:evidence"],
                "limitations": ["Z limitation.", "A limitation."],
            }],
        },
    }
    context = ExplainEngine._repository_context(_snapshot(source)).to_dict()["reachability"]
    reordered = {
        **source,
        "reachability": {
            **source["reachability"],
            "finding_groups": [{
                **source["reachability"]["finding_groups"][0],
                "subject_ids": list(reversed(subject_ids)),
                "evidence_ids": ["a:evidence", "z:evidence"],
                "limitations": ["A limitation.", "Z limitation."],
            }],
        },
    }
    reordered_context = ExplainEngine._repository_context(
        _snapshot(reordered)
    ).to_dict()["reachability"]

    assert context == reordered_context
    assert context["candidate_finding_count"] == 100
    assert context["included_candidate_finding_count"] == 8
    assert context["omitted_candidate_finding_count"] == 92
    assert len(context["representative_findings"]) == 8


def test_framework_evidence_without_scope_is_not_classified_as_test_only() -> None:
    context = ExplainEngine._repository_context(_snapshot({
        "workspace": {"root": "C:/demo"},
        "repository_summary": {
            "root": "C:/demo",
            "projects": [],
            "frameworks": ["Example"],
            "framework_evidence": [{
                "framework": "Example",
                "project": "demo",
                "reference": "org.example:example",
            }, {
                "framework": "Example",
                "project": "tests",
                "scope": "test-only",
                "reference": "org.example:example-tests",
            }],
        },
    })).to_dict()
    item = context["repository_summary"][
        "frameworks_and_related_technologies"
    ]["items"][0]

    assert item["evidence_scopes"] == ["test-only"]
    assert item["classification"] == "framework-or-related-technology-evidence"


def test_default_report_escapes_untrusted_snapshot_metadata() -> None:
    snapshot = _snapshot({
        "workspace": {"root": "C:/<script>"},
        "repository_summary": {
            "root": "C:/<script>",
            "projects": [],
            "frameworks": ["*[unsafe]<img src=x>"],
        },
    })

    markdown = ExplainEngine(
        LlmClient(ScriptedLlmProvider(["unused"]))
    ).explain(snapshot).markdown

    assert "<script>" not in markdown
    assert "<img src=x>" not in markdown
    assert "&lt;script&gt;" in markdown
    assert "\\*\\[unsafe\\]&lt;img src=x&gt;" in markdown


def test_large_repository_projection_is_bounded_and_reproducible() -> None:
    projects = [
        {
            "name": f"project-{index:04d}",
            "path": "." if index == 0 else f"modules/{index:04d}",
            "files": 10,
            "size": 100,
            "build_systems": ["Maven"],
        }
        for index in range(1_500)
    ]
    evidence = [
        {
            "framework": "Example",
            "project": f"project-{index % 1_500:04d}",
            "scope": "project-local",
            "reference": f"org.example:item-{index:05d}",
        }
        for index in range(10_000)
    ]
    hierarchy = [
        {"project": item["name"], "parent": None if index == 0 else "project-0000"}
        for index, item in enumerate(projects)
    ]
    source = {
        "workspace": {"root": "C:/large"},
        "repository_summary": {
            "root": "C:/large",
            "projects": projects,
            "languages": {"Java": 15_000},
            "build_systems": ["Maven"],
            "frameworks": ["Example"],
            "framework_evidence": evidence,
            "module_hierarchy": hierarchy,
        },
    }

    first = ExplainEngine._repository_context(_snapshot(source)).to_json()
    reordered_source = {
        **source,
        "repository_summary": {
            **source["repository_summary"],
            "projects": list(reversed(projects)),
            "framework_evidence": list(reversed(evidence)),
            "module_hierarchy": list(reversed(hierarchy)),
        },
    }
    second = ExplainEngine._repository_context(_snapshot(reordered_source)).to_json()
    projected = ExplainEngine._repository_context(_snapshot(source)).to_dict()
    framework = projected["repository_summary"][
        "frameworks_and_related_technologies"
    ]["items"][0]

    assert first == second
    assert len(first) < 60_000
    assert projected["workspace"]["discovered_project_count"] == 1_500
    assert framework["evidence_count"] == 10_000
    assert len(framework["representative_references"]) == 3
    assert framework["omitted_reference_count"] == 9_997
    hierarchy_projection = projected["repository_summary"]["filesystem_project_hierarchy"]
    assert len(hierarchy_projection["representative_relationships"]) == 25
    assert hierarchy_projection["omitted_relationship_count"] == 1_475


def test_repository_summary_aliases_preserve_legacy_fields(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text("value = 1\n", encoding="utf-8")

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()

    assert payload["schema_version"] == 1
    assert payload["inventoried_file_count"] == sum(
        project["files"] for project in payload["projects"]
    )
    assert payload["inventoried_file_bytes"] == sum(
        project["size"] for project in payload["projects"]
    )
    assert payload["language_file_counts"] == payload["languages"]
    assert payload["classified_non_test_source_files"] == payload["production_files"]
    assert payload["total_declared_dependency_records"] == payload["total_declared_dependencies"]


def test_maven_coordinate_matching_does_not_confuse_reactive_or_integration_names(
    tmp_path: Path,
) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>org.example</groupId><artifactId>demo</artifactId><version>1</version>
          <dependencies>
            <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-spring-di</artifactId></dependency>
            <dependency><groupId>io.quarkus</groupId><artifactId>quarkus-reactive-routes</artifactId></dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()

    assert "Quarkus" in payload["frameworks"]
    assert "Spring" not in payload["frameworks"]
    assert "Spring Boot" not in payload["frameworks"]
    assert "Spring Framework" not in payload["frameworks"]
    assert "React" not in payload["frameworks"]


def test_repository_summary_preserves_real_maven_scope_evidence(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>org.example</groupId><artifactId>demo</artifactId><version>1</version>
          <dependencies>
            <dependency>
              <groupId>org.springframework.boot</groupId>
              <artifactId>spring-boot-starter-test</artifactId>
              <scope>test</scope>
            </dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    evidence = {
        (item["framework"], item["scope"])
        for item in payload["framework_evidence"]
    }

    assert ("Spring Boot", "test-only") in evidence
    assert ("Spring Framework", "test-only") in evidence


def test_nested_fixture_manifest_remains_visible_with_fixture_scope(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "src" / "test" / "fixtures" / "spring"
    fixture.mkdir(parents=True)
    (fixture / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>org.example</groupId><artifactId>fixture</artifactId><version>1</version>
          <dependencies>
            <dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter</artifactId></dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    evidence = {
        (item["framework"], item["scope"])
        for item in payload["framework_evidence"]
    }

    assert ("Spring Boot", "test-or-sample") in evidence
    assert ("Spring Framework", "test-or-sample") in evidence


def test_gradle_framework_coordinates_reuse_coordinate_aware_rules(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "build.gradle").write_text(
        (
            'testImplementation "org.springframework.boot:spring-boot-starter-test:3.5.0"\n'
            'implementation "io.quarkus:quarkus-core:3.24.0"\n'
        ),
        encoding="utf-8",
    )

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    evidence = {
        (item["framework"], item["scope"])
        for item in payload["framework_evidence"]
    }

    assert ("Spring Boot", "test-only") in evidence
    assert ("Spring Framework", "test-only") in evidence
    assert ("Quarkus", "project-local") in evidence


def test_documentation_projects_are_not_labeled_as_tests(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: documentation\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>org.example</groupId><artifactId>docs</artifactId><version>1</version>
          <dependencies>
            <dependency><groupId>org.springframework</groupId><artifactId>spring-core</artifactId></dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()

    assert {item["scope"] for item in payload["framework_evidence"]} == {"documentation"}


def test_non_maven_framework_evidence_preserves_documentation_and_tooling_scope(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    documentation = projects / "documentation"
    tooling = projects / "build-tools"
    documentation.mkdir(parents=True)
    tooling.mkdir(parents=True)
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: documentation\n"
        "    path: projects/documentation\n"
        "  - name: build-tools\n"
        "    path: projects/build-tools\n",
        encoding="utf-8",
    )
    manifest = '{"dependencies":{"react":"19.0.0"}}\n'
    (documentation / "package.json").write_text(manifest, encoding="utf-8")
    (tooling / "package.json").write_text(manifest, encoding="utf-8")

    payload = RepositorySummaryService(WorkspaceService(tmp_path)).build().to_dict()
    scopes_by_project = {
        item["project"]: item["scope"] for item in payload["framework_evidence"]
    }

    assert scopes_by_project == {
        "build-tools": "build-tooling",
        "documentation": "documentation",
    }
