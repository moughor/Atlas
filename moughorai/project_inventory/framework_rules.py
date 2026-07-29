"""Declarative Maven framework detection rules."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.project_inventory.framework_models import FrameworkCategory


@dataclass(frozen=True)
class FrameworkRule:
    """One deterministic Maven coordinate matching rule."""

    name: str
    category: FrameworkCategory
    group_prefixes: tuple[str, ...] = ()
    artifact_prefixes: tuple[str, ...] = ()
    exact_coordinates: tuple[str, ...] = ()
    confidence: float = 1.0

    def matches(self, group_id: str, artifact_id: str) -> bool:
        """Return whether a Maven coordinate satisfies this rule."""

        coordinate = f"{group_id}:{artifact_id}".casefold()
        normalized_group = group_id.casefold()
        normalized_artifact = artifact_id.casefold()

        if any(
            coordinate == expected.casefold()
            for expected in self.exact_coordinates
        ):
            return True

        has_group_rules = bool(self.group_prefixes)
        has_artifact_rules = bool(self.artifact_prefixes)

        group_match = (
            has_group_rules
            and any(
                normalized_group.startswith(prefix.casefold())
                for prefix in self.group_prefixes
            )
        )
        artifact_match = (
            has_artifact_rules
            and any(
                normalized_artifact.startswith(prefix.casefold())
                for prefix in self.artifact_prefixes
            )
        )

        if has_group_rules and has_artifact_rules:
            return group_match and artifact_match

        if has_group_rules:
            return group_match

        if has_artifact_rules:
            return artifact_match

        return False


FRAMEWORK_RULES: tuple[FrameworkRule, ...] = (
    FrameworkRule(
        name="Spring Boot",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=("org.springframework.boot",),
    ),
    FrameworkRule(
        name="Spring Framework",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=("org.springframework",),
    ),
    FrameworkRule(
        name="Spring Security",
        category=FrameworkCategory.SECURITY,
        group_prefixes=("org.springframework.security",),
    ),
    FrameworkRule(
        name="Hibernate",
        category=FrameworkCategory.PERSISTENCE,
        group_prefixes=("org.hibernate",),
    ),
    FrameworkRule(
        name="Jakarta Persistence",
        category=FrameworkCategory.PERSISTENCE,
        group_prefixes=("jakarta.persistence",),
    ),
    FrameworkRule(
        name="Jakarta EE",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=(
            "jakarta.platform",
            "jakarta.enterprise",
            "jakarta.servlet",
            "jakarta.ejb",
        ),
    ),
    FrameworkRule(
        name="Oracle JDBC",
        category=FrameworkCategory.DATABASE,
        group_prefixes=(
            "com.oracle.database.jdbc",
            "com.oracle.jdbc",
        ),
        artifact_prefixes=("ojdbc",),
    ),
    FrameworkRule(
        name="PostgreSQL",
        category=FrameworkCategory.DATABASE,
        exact_coordinates=("org.postgresql:postgresql",),
    ),
    FrameworkRule(
        name="MySQL",
        category=FrameworkCategory.DATABASE,
        exact_coordinates=(
            "com.mysql:mysql-connector-j",
            "mysql:mysql-connector-java",
        ),
    ),
    FrameworkRule(
        name="MariaDB",
        category=FrameworkCategory.DATABASE,
        exact_coordinates=("org.mariadb.jdbc:mariadb-java-client",),
    ),
    FrameworkRule(
        name="H2",
        category=FrameworkCategory.DATABASE,
        exact_coordinates=("com.h2database:h2",),
    ),
    FrameworkRule(
        name="Flyway",
        category=FrameworkCategory.MIGRATION,
        group_prefixes=("org.flywaydb",),
    ),
    FrameworkRule(
        name="Liquibase",
        category=FrameworkCategory.MIGRATION,
        group_prefixes=("org.liquibase",),
    ),
    FrameworkRule(
        name="Log4j2",
        category=FrameworkCategory.LOGGING,
        group_prefixes=("org.apache.logging.log4j",),
    ),
    FrameworkRule(
        name="Logback",
        category=FrameworkCategory.LOGGING,
        group_prefixes=("ch.qos.logback",),
    ),
    FrameworkRule(
        name="SLF4J",
        category=FrameworkCategory.LOGGING,
        group_prefixes=("org.slf4j",),
    ),
    FrameworkRule(
        name="JUnit 5",
        category=FrameworkCategory.TESTING,
        group_prefixes=("org.junit.jupiter",),
    ),
    FrameworkRule(
        name="JUnit 4",
        category=FrameworkCategory.TESTING,
        exact_coordinates=("junit:junit",),
    ),
    FrameworkRule(
        name="Mockito",
        category=FrameworkCategory.TESTING,
        group_prefixes=("org.mockito",),
    ),
    FrameworkRule(
        name="AssertJ",
        category=FrameworkCategory.TESTING,
        group_prefixes=("org.assertj",),
    ),
    FrameworkRule(
        name="Testcontainers",
        category=FrameworkCategory.TESTING,
        group_prefixes=("org.testcontainers",),
    ),
    FrameworkRule(
        name="Quarkus",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=("io.quarkus",),
    ),
    FrameworkRule(
        name="Micronaut",
        category=FrameworkCategory.FRAMEWORK,
        group_prefixes=("io.micronaut",),
    ),
    FrameworkRule(
        name="Jakarta REST",
        category=FrameworkCategory.API,
        group_prefixes=("jakarta.ws.rs",),
    ),
    FrameworkRule(
        name="RESTEasy",
        category=FrameworkCategory.API,
        group_prefixes=("org.jboss.resteasy",),
    ),
    FrameworkRule(
        name="Apache CXF",
        category=FrameworkCategory.API,
        group_prefixes=("org.apache.cxf",),
    ),
    FrameworkRule(
        name="Kafka",
        category=FrameworkCategory.MESSAGING,
        group_prefixes=("org.apache.kafka",),
    ),
    FrameworkRule(
        name="RabbitMQ",
        category=FrameworkCategory.MESSAGING,
        group_prefixes=("com.rabbitmq",),
    ),
)
