import json
from pathlib import Path

import pytest

from moughorai.java_security import (
    JavaConfigurationParser,
    JavaProjectInput,
    JavaSecurityAnalyzer,
    JavaSecurityParser,
    JavaSourceUnit,
)
from moughorai.security_analysis import SecurityReportExporter, ValueKind


def scan(body: str):
    return JavaSecurityAnalyzer().analyze_source(body, "src/main/java/App.java")


@pytest.mark.parametrize(
    "source,sink,rule",
    [
        ('request.getParameter("q")', 'statement.executeQuery(value)', 'ATLAS-SQL-001'),
        ('request.getHeader("X-Cmd")', 'Runtime.getRuntime().exec(value)', 'ATLAS-CMD-001'),
        ('request.getParameter("file")', 'Files.readAllBytes(value)', 'ATLAS-PATH-001'),
        ('request.getParameter("url")', 'URL.openConnection(value)', 'ATLAS-SSRF-001'),
        ('request.getInputStream()', 'ObjectInputStream.readObject(value)', 'ATLAS-DESER-001'),
        ('request.getParameter("class")', 'Class.forName(value)', 'ATLAS-REFLECT-001'),
    ],
)
def test_java_taint_source_to_sink(source, sink, rule):
    report = scan(f"String value = {source};\n{sink};")
    assert [finding.rule_id for finding in report.findings] == [rule]


@pytest.mark.parametrize(
    "source",
    [
        'request.getParameter("x")',
        'request.getHeader("x")',
        'request.getQueryString()',
        'scanner.nextLine()',
        'System.getenv("X")',
        'System.getProperty("x")',
        'reader.readLine()',
        'request.getInputStream()',
    ],
)
def test_supported_java_sources(source):
    assert scan(f"String x = {source}; Runtime.getRuntime().exec(x);").findings


@pytest.mark.parametrize("sanitizer", ["sanitize", "escapeSql", "normalizePath", "validateUrl", "allowlist", "encodeForSQL"])
def test_java_sanitizers(sanitizer):
    report = scan(
        f'String x = request.getParameter("x");\n'
        f'String safe = {sanitizer}(x);\n'
        'Runtime.getRuntime().exec(safe);'
    )
    assert not report.findings


def test_string_concatenation_propagates_taint():
    report = scan(
        'String input = request.getParameter("name");\n'
        'String query = "select * from users where name=" + input;\n'
        'statement.executeQuery(query);'
    )
    assert report.findings[0].rule_id == "ATLAS-SQL-001"
    assert report.findings[0].location.line == 3


def test_literal_sink_is_safe():
    assert not scan('Runtime.getRuntime().exec("date");').findings


def test_comments_are_ignored():
    report = scan(
        '// Runtime.getRuntime().exec(request.getParameter("x"));\n'
        '/* statement.executeQuery(request.getParameter("q")); */\n'
        'String x = "safe";'
    )
    assert not report.findings


def test_multiline_call_is_parsed():
    report = scan(
        'String value = request.getParameter(\n'
        '  "cmd"\n'
        ');\n'
        'Runtime.getRuntime().exec(\n'
        ' value\n'
        ');'
    )
    assert report.findings[0].rule_id == "ATLAS-CMD-001"
    assert report.findings[0].location.line == 4


def test_nested_call_source():
    report = scan('Runtime.getRuntime().exec(request.getParameter("cmd"));')
    assert report.findings[0].rule_id == "ATLAS-CMD-001"


def test_hardcoded_secret_in_java():
    report = scan('String password = "password=supersecret123";')
    assert report.findings[0].rule_id == "ATLAS-SECRET-001"


@pytest.mark.parametrize("algorithm", ["MD5", "SHA-1", "DES", "RC4", "AES/ECB/PKCS5Padding"])
def test_weak_crypto_in_java(algorithm):
    report = scan(f'MessageDigest.getInstance("{algorithm}");')
    assert report.findings[0].rule_id == "ATLAS-CRYPTO-001"


def test_strong_crypto_in_java_is_safe():
    assert not scan('MessageDigest.getInstance("SHA-256");').findings


def test_xxe_in_java():
    assert scan('builder.parse(input);').findings[0].rule_id == "ATLAS-XXE-001"


def test_annotation_collection():
    parsed = JavaSecurityParser().parse(JavaSourceUnit("A.java", "@RestController\nclass A {}"))
    assert parsed.program.annotations == ("RestController",)


def test_assignment_types_and_final_modifier():
    parsed = JavaSecurityParser().parse(
        JavaSourceUnit("A.java", 'final java.lang.String value = request.getParameter("x");')
    )
    assert parsed.program.assignments[0].target == "value"


def test_boolean_and_numeric_literals():
    parsed = JavaSecurityParser().parse(JavaSourceUnit("A.java", "boolean a = false; int b = 42;"))
    assert parsed.program.assignments[0].value.value is False
    assert parsed.program.assignments[1].value.value == 42


def test_unknown_expression_kind():
    parsed = JavaSecurityParser().parse(JavaSourceUnit("A.java", "String x = items[index];"))
    assert parsed.program.assignments[0].value.kind is ValueKind.UNKNOWN


def test_properties_configuration():
    values = dict(JavaConfigurationParser().parse(
        "src/main/resources/application.properties",
        "spring.security.csrf.enabled=false\nserver.ssl.enabled=false\n",
    ))
    assert values["spring.security.csrf.enabled"] == "false"
    assert values["config_path"].endswith("application.properties")


def test_properties_comments_and_colon_separator():
    values = dict(JavaConfigurationParser().parse("application.properties", "# note\nserver.ssl.enabled: false\n"))
    assert values["server.ssl.enabled"] == "false"


def test_yaml_configuration():
    values = dict(JavaConfigurationParser().parse(
        "application.yml",
        "spring:\n  security:\n    csrf:\n      enabled: false\n",
    ))
    assert values["spring.security.csrf.enabled"] == "false"


@pytest.mark.parametrize(
    "path,content,rule",
    [
        ("application.properties", "spring.security.csrf.enabled=false", "ATLAS-SPRING-001"),
        ("application.yml", "server:\n  ssl:\n    enabled: false", "ATLAS-CONFIG-001"),
        ("application.yaml", "management:\n  endpoints:\n    web:\n      exposure:\n        include: '*'", "ATLAS-SPRING-002"),
    ],
)
def test_project_configuration_findings(path, content, rule):
    project = JavaProjectInput(configurations=((path, content),))
    result = JavaSecurityAnalyzer().analyze_project(project)
    assert result.report.findings[0].rule_id == rule
    assert result.configuration_files == 1


def test_project_combines_multiple_sources():
    project = JavaProjectInput(sources=(
        JavaSourceUnit("A.java", 'String x = request.getParameter("x"); Runtime.getRuntime().exec(x);'),
        JavaSourceUnit("B.java", 'String q = request.getParameter("q"); statement.executeQuery(q);'),
    ))
    result = JavaSecurityAnalyzer().analyze_project(project)
    assert {finding.rule_id for finding in result.report.findings} == {"ATLAS-CMD-001", "ATLAS-SQL-001"}
    assert result.source_files == 2


def test_project_order_is_deterministic():
    project = JavaProjectInput(sources=(
        JavaSourceUnit("z/Z.java", 'String x = request.getParameter("x"); Runtime.getRuntime().exec(x);'),
        JavaSourceUnit("a/A.java", 'String q = request.getParameter("q"); statement.executeQuery(q);'),
    ))
    paths = [finding.location.path for finding in JavaSecurityAnalyzer().analyze_project(project).report.findings]
    assert paths == sorted(paths)


def test_rule_summary():
    report = scan(
        'String x = request.getParameter("x");\n'
        'Runtime.getRuntime().exec(x);\n'
        'statement.executeQuery(x);'
    )
    assert JavaSecurityAnalyzer().rule_summary(report) == (("ATLAS-CMD-001", 1), ("ATLAS-SQL-001", 1))


def test_json_export_from_java_report():
    report = scan('String x = request.getParameter("x"); Runtime.getRuntime().exec(x);')
    payload = json.loads(SecurityReportExporter().to_json(report))
    assert payload["findings"][0]["location"]["path"] == "src/main/java/App.java"


def test_sarif_export_from_java_report():
    report = scan('String x = request.getParameter("x"); Runtime.getRuntime().exec(x);')
    payload = json.loads(SecurityReportExporter().to_sarif(report))
    assert payload["runs"][0]["results"][0]["ruleId"] == "ATLAS-CMD-001"


def test_parse_warning_for_security_relevant_unsupported_statement():
    parser = JavaSecurityParser(warn_on_unsupported=True)
    parsed = parser.parse(JavaSourceUnit("A.java", "return executeSomething;"))
    assert parsed.warnings


def test_no_warning_by_default():
    parsed = JavaSecurityParser().parse(JavaSourceUnit("A.java", "return executeSomething;"))
    assert not parsed.warnings


def test_invalid_source_path():
    with pytest.raises(ValueError):
        JavaSourceUnit("", "class A {}")


def test_directory_input(tmp_path: Path):
    java = tmp_path / "src" / "App.java"
    java.parent.mkdir()
    java.write_text('String x = request.getParameter("x"); Runtime.getRuntime().exec(x);', encoding="utf-8")
    resources = tmp_path / "src" / "application.properties"
    resources.write_text("server.ssl.enabled=false", encoding="utf-8")
    project = JavaProjectInput.from_directory(tmp_path)
    assert len(project.sources) == 1
    assert len(project.configurations) == 1
    result = JavaSecurityAnalyzer().analyze_project(project)
    assert {f.rule_id for f in result.report.findings} == {"ATLAS-CMD-001", "ATLAS-CONFIG-001"}


def test_directory_input_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        JavaProjectInput.from_directory(tmp_path / "missing")


def test_windows_paths_normalized(tmp_path: Path):
    source = tmp_path / "nested" / "App.java"
    source.parent.mkdir()
    source.write_text("class App {}", encoding="utf-8")
    project = JavaProjectInput.from_directory(tmp_path)
    assert "\\" not in project.sources[0].path


def test_duplicate_finding_same_location_is_deduplicated():
    report = scan(
        'String x = request.getParameter("x");\n'
        'Runtime.getRuntime().exec(x); Runtime.getRuntime().exec(x);'
    )
    assert len(report.findings) == 1


def test_trace_contains_java_source_and_sink():
    finding = scan('String x = request.getParameter("x"); Runtime.getRuntime().exec(x);').findings[0]
    assert len(finding.trace) == 2
    assert finding.trace[0].location.path.endswith("App.java")


def test_config_path_preserved_in_finding():
    project = JavaProjectInput(configurations=(("config/application.properties", "server.ssl.enabled=false"),))
    finding = JavaSecurityAnalyzer().analyze_project(project).report.findings[0]
    assert finding.location.path == "config/application.properties"


def test_source_and_configuration_counts_empty_project():
    result = JavaSecurityAnalyzer().analyze_project(JavaProjectInput())
    assert result.source_files == 0
    assert result.configuration_files == 0
    assert not result.report.findings
