from pathlib import Path
from moughorai.java_spring import InjectionKind, SpringAnalysisService, SpringBeanKind

def sources():
    return {
        Path("src/UserRepository.java"): '''package app; import org.springframework.stereotype.Repository; @Repository public interface UserRepository {}''',
        Path("src/UserService.java"): '''package app; import org.springframework.stereotype.Service; @Service public class UserService { private final UserRepository repository; public UserService(UserRepository repository) {} }''',
        Path("src/UserController.java"): '''package app; import org.springframework.web.bind.annotation.RestController; import org.springframework.web.bind.annotation.GetMapping; @RestController public class UserController { private final UserService service; public UserController(UserService service) {} @GetMapping public String get() { return "x"; } }''',
    }

def test_detects_spring_stereotype_beans():
    report = SpringAnalysisService().analyze_sources(sources())
    assert report.bean("app.UserService").kind is SpringBeanKind.SERVICE
    assert report.bean("app.UserRepository").kind is SpringBeanKind.REPOSITORY
    assert report.bean("app.UserController").kind is SpringBeanKind.REST_CONTROLLER

def test_detects_single_constructor_injection():
    report = SpringAnalysisService().analyze_sources(sources())
    deps = report.dependencies("app.UserService")
    assert len(deps) == 1
    assert deps[0].kind is InjectionKind.CONSTRUCTOR
    assert deps[0].target_qualified_name == "app.UserRepository"

def test_detects_reverse_dependents():
    report = SpringAnalysisService().analyze_sources(sources())
    points = report.dependents("app.UserService")
    assert tuple(p.owner for p in points) == ("app.UserController",)

def test_detects_annotated_field_injection():
    data = {Path("A.java"): '''package app; class Dep {} class A { @org.springframework.beans.factory.annotation.Autowired Dep dep; }'''}
    report = SpringAnalysisService().analyze_sources(data)
    point = report.dependencies("app.A")[0]
    assert point.kind is InjectionKind.FIELD
    assert point.target_qualified_name == "app.Dep"

def test_detects_mapping_methods():
    report = SpringAnalysisService().analyze_sources(sources())
    endpoint = report.endpoints_for("app.UserController")[0]
    assert endpoint.method_name == "get"
    assert endpoint.http_methods == ("GET",)

def test_unresolved_injection_is_preserved():
    data = {Path("A.java"): '''package app; class A { public A(MissingService service) {} }'''}
    point = SpringAnalysisService().analyze_sources(data).dependencies("app.A")[0]
    assert point.target_name == "MissingService"
    assert point.target_qualified_name is None
