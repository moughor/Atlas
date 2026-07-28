from pathlib import Path

from moughorai.project_inventory.framework_service import (
    MavenFrameworkService,
)


def test_service_parses_and_detects_frameworks(tmp_path: Path) -> None:
    pom = tmp_path / "pom.xml"
    pom.write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>com.demo</groupId>
          <artifactId>demo</artifactId>
          <version>1.0</version>
          <dependencies>
            <dependency>
              <groupId>org.springframework.boot</groupId>
              <artifactId>spring-boot-starter-web</artifactId>
            </dependency>
            <dependency>
              <groupId>org.hibernate.orm</groupId>
              <artifactId>hibernate-core</artifactId>
            </dependency>
          </dependencies>
        </project>
        """,
        encoding="utf-8",
    )

    report = MavenFrameworkService().analyze(pom)

    assert report.has("Spring Boot")
    assert report.has("Spring Framework")
    assert report.has("Hibernate")
