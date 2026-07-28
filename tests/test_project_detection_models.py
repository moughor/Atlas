from pathlib import Path

import pytest

from moughorai.project_inventory.detection_models import (
    DetectedTechnology,
    ProjectDetection,
    TechnologyCategory,
)


def test_detected_technology_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        DetectedTechnology(
            name="Maven",
            category=TechnologyCategory.BUILD,
            confidence=1.1,
            evidence=(Path("pom.xml"),),
        )


def test_project_detection_filters_by_name_and_category() -> None:
    maven = DetectedTechnology(
        name="Maven",
        category=TechnologyCategory.BUILD,
        confidence=1.0,
        evidence=(Path("pom.xml"),),
    )
    java = DetectedTechnology(
        name="Java",
        category=TechnologyCategory.LANGUAGE,
        confidence=1.0,
        evidence=(Path("src/App.java"),),
    )
    detection = ProjectDetection((maven, java))

    assert detection.has("maven")
    assert detection.by_category(TechnologyCategory.BUILD) == (maven,)
