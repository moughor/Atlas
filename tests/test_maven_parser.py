from pathlib import Path

import pytest

from moughorai.project_inventory.maven_parser import (
    MavenParseError,
    MavenParser,
)


def write_pom(tmp_path: Path, content: str, name: str = "pom.xml") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parser_reads_minimal_pom(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <modelVersion>4.0.0</modelVersion>
          <groupId>com.demo</groupId>
          <artifactId>demo</artifactId>
          <version>1.0.0</version>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.model_version == "4.0.0"
    assert project.group_id == "com.demo"
    assert project.artifact_id == "demo"
    assert project.version == "1.0.0"
    assert project.packaging == "jar"
    assert project.dependencies == ()


def test_parser_handles_default_maven_namespace(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modelVersion>4.0.0</modelVersion>
          <groupId>com.demo</groupId>
          <artifactId>namespaced</artifactId>
          <version>2.0</version>
          <packaging>war</packaging>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.artifact_id == "namespaced"
    assert project.packaging == "war"


def test_parser_reads_parent_and_inherited_values(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <parent>
            <groupId>com.demo</groupId>
            <artifactId>parent</artifactId>
            <version>3.0</version>
            <relativePath>../pom.xml</relativePath>
          </parent>
          <artifactId>child</artifactId>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.parent is not None
    assert project.parent.relative_path == "../pom.xml"
    assert project.effective_group_id == "com.demo"
    assert project.effective_version == "3.0"


def test_parser_reads_dependencies_and_managed_dependencies(
    tmp_path: Path,
) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <dependencyManagement>
            <dependencies>
              <dependency>
                <groupId>org.hibernate.orm</groupId>
                <artifactId>hibernate-core</artifactId>
                <version>6.6.0</version>
              </dependency>
            </dependencies>
          </dependencyManagement>
          <dependencies>
            <dependency>
              <groupId>org.springframework.boot</groupId>
              <artifactId>spring-boot-starter-web</artifactId>
              <version>${spring.version}</version>
              <scope>compile</scope>
              <optional>true</optional>
            </dependency>
            <dependency>
              <groupId>org.junit.jupiter</groupId>
              <artifactId>junit-jupiter</artifactId>
              <scope>test</scope>
            </dependency>
          </dependencies>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert len(project.dependencies) == 2
    assert project.dependencies[0].identifier == (
        "org.springframework.boot:spring-boot-starter-web"
    )
    assert project.dependencies[0].version == "${spring.version}"
    assert project.dependencies[0].scope == "compile"
    assert project.dependencies[0].optional is True
    assert project.dependencies[1].version is None
    assert project.managed_dependencies[0].identifier == (
        "org.hibernate.orm:hibernate-core"
    )


def test_parser_reads_plugins_with_default_group(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <build>
            <plugins>
              <plugin>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.13.0</version>
              </plugin>
              <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
              </plugin>
            </plugins>
          </build>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.plugins[0].group_id == "org.apache.maven.plugins"
    assert project.plugins[0].artifact_id == "maven-compiler-plugin"
    assert project.plugins[1].group_id == "org.springframework.boot"


def test_parser_reads_properties_and_modules(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <properties>
            <java.version>21</java.version>
            <spring.version>3.5.0</spring.version>
          </properties>
          <modules>
            <module>api</module>
            <module>core</module>
          </modules>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.property_value("java.version") == "21"
    assert [module.path for module in project.modules] == ["api", "core"]


def test_parser_skips_incomplete_dependency(tmp_path: Path) -> None:
    pom = write_pom(
        tmp_path,
        """
        <project>
          <dependencies>
            <dependency>
              <artifactId>missing-group</artifactId>
            </dependency>
          </dependencies>
        </project>
        """,
    )

    project = MavenParser().parse(pom)

    assert project.dependencies == ()


def test_parser_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MavenParseError):
        MavenParser().parse(tmp_path / "missing.xml")


def test_parser_rejects_invalid_xml(tmp_path: Path) -> None:
    pom = write_pom(tmp_path, "<project>")

    with pytest.raises(MavenParseError):
        MavenParser().parse(pom)


def test_parse_many_is_deterministic(tmp_path: Path) -> None:
    second = write_pom(
        tmp_path,
        "<project><artifactId>second</artifactId></project>",
        "z-pom.xml",
    )
    first = write_pom(
        tmp_path,
        "<project><artifactId>first</artifactId></project>",
        "a-pom.xml",
    )

    projects = MavenParser().parse_many([second, first])

    assert [project.artifact_id for project in projects] == [
        "first",
        "second",
    ]
