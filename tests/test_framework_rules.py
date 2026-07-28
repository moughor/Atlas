from moughorai.project_inventory.framework_models import FrameworkCategory
from moughorai.project_inventory.framework_rules import FrameworkRule


def test_rule_matches_group_prefix() -> None:
    rule = FrameworkRule(
        name="Spring",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=("org.springframework",),
    )

    assert rule.matches(
        "org.springframework.boot",
        "spring-boot-starter",
    )
    assert not rule.matches("org.hibernate", "hibernate-core")


def test_rule_matches_exact_coordinate() -> None:
    rule = FrameworkRule(
        name="PostgreSQL",
        category=FrameworkCategory.DATABASE,
        exact_coordinates=("org.postgresql:postgresql",),
    )

    assert rule.matches("org.postgresql", "postgresql")
    assert not rule.matches("org.postgresql", "other")


def test_rule_combines_group_and_artifact_prefixes() -> None:
    rule = FrameworkRule(
        name="Oracle JDBC",
        category=FrameworkCategory.DATABASE,
        group_prefixes=("com.oracle.database.jdbc",),
        artifact_prefixes=("ojdbc",),
    )

    assert rule.matches("com.oracle.database.jdbc", "ojdbc11")
    assert not rule.matches(
        "com.oracle.database.jdbc",
        "ucp",
    )
