from pathlib import Path

import pytest

from moughorai.project_inventory.framework_models import (
    DetectedFramework,
    FrameworkCategory,
    FrameworkEvidence,
    FrameworkReport,
)


def test_detected_framework_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        DetectedFramework(
            name="Spring Boot",
            category=FrameworkCategory.FRAMEWORK,
            confidence=1.1,
            evidence=(),
        )


def test_report_filters_and_finds_technologies() -> None:
    spring = DetectedFramework(
        name="Spring Boot",
        category=FrameworkCategory.FRAMEWORK,
        confidence=1.0,
        evidence=(
            FrameworkEvidence(
                coordinate=(
                    "org.springframework.boot:"
                    "spring-boot-starter-web"
                ),
                source=Path("pom.xml"),
            ),
        ),
    )
    report = FrameworkReport(
        source=Path("pom.xml"),
        technologies=(spring,),
    )

    assert report.has("spring boot")
    assert report.get("SPRING BOOT") == spring
    assert report.by_category(
        FrameworkCategory.FRAMEWORK
    ) == (spring,)
    assert spring.coordinates == (
        "org.springframework.boot:spring-boot-starter-web",
    )
