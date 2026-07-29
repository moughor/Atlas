from pathlib import Path
from moughorai.java_jpa import JpaAnalysisService, JpaRelationKind


def sources():
    return {
        Path("src/User.java"): '''package app; import jakarta.persistence.*; @Entity public class User { @Id @GeneratedValue Long id; String name; @ManyToOne Department department; @Transient String scratch; }''',
        Path("src/Department.java"): '''package app; import jakarta.persistence.*; import java.util.List; @Entity public class Department { @Id Long id; @OneToMany List<User> users; }''',
    }


def test_detects_entities_and_default_table_names():
    report = JpaAnalysisService().analyze_sources(sources())
    assert report.entity("app.User").table_name == "User"
    assert report.entity("app.Department").table_name == "Department"


def test_detects_id_generated_and_basic_attributes():
    report = JpaAnalysisService().analyze_sources(sources())
    attrs = report.attributes_for("app.User")
    assert tuple(a.name for a in attrs) == ("id", "name")
    assert attrs[0].is_id
    assert attrs[0].generated


def test_ignores_transient_fields():
    report = JpaAnalysisService().analyze_sources(sources())
    assert "scratch" not in {a.name for a in report.attributes_for("app.User")}


def test_detects_many_to_one_relation():
    relation = JpaAnalysisService().analyze_sources(sources()).relations_for("app.User")[0]
    assert relation.kind is JpaRelationKind.MANY_TO_ONE
    assert relation.target_qualified_name == "app.Department"


def test_resolves_collection_element_relation_target():
    relation = JpaAnalysisService().analyze_sources(sources()).relations_for("app.Department")[0]
    assert relation.kind is JpaRelationKind.ONE_TO_MANY
    assert relation.target_name == "User"
    assert relation.target_qualified_name == "app.User"


def test_reverse_relation_dependents():
    report = JpaAnalysisService().analyze_sources(sources())
    assert tuple(r.owner for r in report.dependents("app.User")) == ("app.Department",)


def test_unresolved_relation_is_preserved():
    data = {Path("A.java"): '''package app; import jakarta.persistence.*; @Entity class A { @ManyToOne Missing missing; }'''}
    relation = JpaAnalysisService().analyze_sources(data).relations_for("app.A")[0]
    assert relation.target_name == "Missing"
    assert relation.target_qualified_name is None
