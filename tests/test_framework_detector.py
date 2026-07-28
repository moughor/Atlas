from pathlib import Path

from moughorai.project_inventory.framework_detector import (
    MavenFrameworkDetector,
)
from moughorai.project_inventory.framework_models import FrameworkCategory
from moughorai.project_inventory.maven_models import (
    MavenDependency,
    MavenPlugin,
    MavenProject,
)


def project(
    *,
    dependencies: tuple[MavenDependency, ...] = (),
    managed_dependencies: tuple[MavenDependency, ...] = (),
    plugins: tuple[MavenPlugin, ...] = (),
    path: str = "pom.xml",
) -> MavenProject:
    return MavenProject(
        pom_path=Path(path),
        model_version="4.0.0",
        group_id="com.demo",
        artifact_id="demo",
        version="1.0",
        packaging="jar",
        name=None,
        parent=None,
        properties=(),
        dependencies=dependencies,
        managed_dependencies=managed_dependencies,
        plugins=plugins,
        modules=(),
    )


def dependency(
    group_id: str,
    artifact_id: str,
    *,
    version: str | None = None,
    scope: str | None = None,
) -> MavenDependency:
    return MavenDependency(
        group_id=group_id,
        artifact_id=artifact_id,
        version=version,
        scope=scope,
    )


def test_detector_detects_spring_boot_and_spring_framework() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(
                dependency(
                    "org.springframework.boot",
                    "spring-boot-starter-web",
                    version="3.5.0",
                ),
            )
        )
    )

    assert report.has("Spring Boot")
    assert report.has("Spring Framework")


def test_detector_detects_persistence_and_database() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(
                dependency("org.hibernate.orm", "hibernate-core"),
                dependency(
                    "com.oracle.database.jdbc",
                    "ojdbc11",
                ),
            )
        )
    )

    assert report.has("Hibernate")
    assert report.has("Oracle JDBC")
    assert len(
        report.by_category(FrameworkCategory.DATABASE)
    ) == 1


def test_detector_detects_testing_logging_and_migration() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(
                dependency(
                    "org.junit.jupiter",
                    "junit-jupiter",
                    scope="test",
                ),
                dependency("org.mockito", "mockito-core"),
                dependency(
                    "org.apache.logging.log4j",
                    "log4j-core",
                ),
                dependency("org.flywaydb", "flyway-core"),
            )
        )
    )

    assert report.has("JUnit 5")
    assert report.has("Mockito")
    assert report.has("Log4j2")
    assert report.has("Flyway")


def test_detector_reads_managed_dependencies() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            managed_dependencies=(
                dependency("org.postgresql", "postgresql"),
            )
        )
    )

    assert report.has("PostgreSQL")


def test_detector_reads_plugins() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            plugins=(
                MavenPlugin(
                    group_id="org.springframework.boot",
                    artifact_id="spring-boot-maven-plugin",
                    version="3.5.0",
                ),
            )
        )
    )

    spring_boot = report.get("Spring Boot")

    assert spring_boot is not None
    assert spring_boot.evidence[0].kind == "plugin"


def test_detector_deduplicates_evidence() -> None:
    duplicate = dependency(
        "org.junit.jupiter",
        "junit-jupiter",
        version="5.11.0",
        scope="test",
    )
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(duplicate,),
            managed_dependencies=(duplicate,),
        )
    )

    junit = report.get("JUnit 5")

    assert junit is not None
    assert len(junit.evidence) == 1


def test_detector_preserves_version_scope_and_source() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(
                dependency(
                    "org.junit.jupiter",
                    "junit-jupiter",
                    version="5.11.0",
                    scope="test",
                ),
            ),
            path="module/pom.xml",
        )
    )

    junit = report.get("JUnit 5")

    assert junit is not None
    assert junit.evidence[0].version == "5.11.0"
    assert junit.evidence[0].scope == "test"
    assert junit.evidence[0].source == Path("module/pom.xml")


def test_detector_order_is_deterministic() -> None:
    report = MavenFrameworkDetector().detect(
        project(
            dependencies=(
                dependency("org.mockito", "mockito-core"),
                dependency("org.flywaydb", "flyway-core"),
                dependency(
                    "org.springframework.boot",
                    "spring-boot-starter-web",
                ),
            )
        )
    )

    ordering = [
        (item.category.value, item.name.casefold())
        for item in report.technologies
    ]

    assert ordering == sorted(ordering)


def test_detect_many_orders_reports_by_path() -> None:
    reports = MavenFrameworkDetector().detect_many(
        [
            project(path="z/pom.xml"),
            project(path="a/pom.xml"),
        ]
    )

    assert [report.source for report in reports] == [
        Path("a/pom.xml"),
        Path("z/pom.xml"),
    ]
