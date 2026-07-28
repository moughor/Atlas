from __future__ import annotations
import pytest
from moughorai.framework_models import Framework, FrameworkAwareAnalyzer, FrameworkDetector, PROFILES
from moughorai.interprocedural_taint import InterproceduralTaintAnalyzer
from moughorai.java_security import JavaSourceUnit
from moughorai.security_analysis.rules import SOURCES, SANITIZERS, TAINT_RULES

def u(text,path='A.java'): return JavaSourceUnit(path,text)

@pytest.mark.parametrize('marker,framework',[
 ('import org.springframework.web.bind.annotation.*;',Framework.SPRING_WEB),
 ('import org.springframework.security.config.annotation.web.builders.HttpSecurity;',Framework.SPRING_SECURITY),
 ('import jakarta.servlet.http.HttpServletRequest;',Framework.SERVLET),
 ('import java.sql.Connection;',Framework.JDBC),
 ('import jakarta.persistence.EntityManager;',Framework.JPA),
 ('import com.fasterxml.jackson.databind.ObjectMapper;',Framework.JACKSON),
 ('import com.google.gson.Gson;',Framework.GSON),
])
def test_detects_framework(marker,framework):
 assert framework in FrameworkDetector().detect((u(marker),)).frameworks

@pytest.mark.parametrize('framework',[f for f in Framework])
def test_detection_is_deterministic(framework):
 profile=next(p for p in PROFILES if p.framework is framework)
 a=FrameworkDetector().detect((u(profile.markers[0]),))
 b=FrameworkDetector().detect((u(profile.markers[0]),))
 assert a==b

@pytest.mark.parametrize('source',[ 'RequestParam','PathVariable','RequestHeader','Authentication.getName','Principal.getName','Jwt.getClaim','getParameter','getHeader','getQueryString','getInputStream'])
def test_framework_sources_flow(source):
 marker='import org.springframework.web.bind.annotation.*; import org.springframework.security.core.Authentication; import jakarta.servlet.*;'
 report=FrameworkAwareAnalyzer().analyze_units((u(f'{marker} class A {{ @GetMapping void go(){{ String x={source}("q"); statement.executeQuery(x); }} }}'),))
 assert report.taint_report.findings

@pytest.mark.parametrize('sanitizer',[ 'HtmlUtils.htmlEscape','UriUtils.encode','PasswordEncoder.encode','PreparedStatement.setString','NamedParameterJdbcTemplate.query'])
def test_framework_sanitizers_cut_flow(sanitizer):
 marker='import org.springframework.web.bind.annotation.*; import org.springframework.security.*; import java.sql.*;'
 r=FrameworkAwareAnalyzer().analyze_units((u(f'{marker} class A {{ @GetMapping void go(){{ String x=RequestParam("q"); String y={sanitizer}(x); statement.executeQuery(y); }} }}'),))
 assert r.taint_report.findings==()

@pytest.mark.parametrize('marker,sink,rule',[
 ('import org.springframework.web.bind.annotation.*;','ExpressionParser.parseExpression','ATLAS-SPRING-SPEL-001'),
 ('import jakarta.persistence.EntityManager;','EntityManager.createQuery','ATLAS-JPA-QUERY-001'),
 ('import org.hibernate.Session;','Session.createQuery','ATLAS-JPA-QUERY-001'),
 ('import com.fasterxml.jackson.databind.ObjectMapper;','ObjectMapper.readValue','ATLAS-JACKSON-TYPE-001'),
 ('import com.fasterxml.jackson.databind.ObjectMapper;','ObjectMapper.treeToValue','ATLAS-JACKSON-TYPE-001'),
 ('import com.google.gson.Gson;','Gson.fromJson','ATLAS-GSON-DESER-001'),
])
def test_framework_specific_sinks(marker,sink,rule):
 src=f'{marker} import org.springframework.web.bind.annotation.*; class A {{ @GetMapping void go(){{ String x=RequestParam("q"); {sink}(x); }} }}'
 r=FrameworkAwareAnalyzer().analyze_units((u(src),))
 assert [f.rule_id for f in r.taint_report.findings]==[rule]

@pytest.mark.parametrize('annotation',['GetMapping','PostMapping','PutMapping','DeleteMapping','PatchMapping','RequestMapping','WebServlet','Path'])
def test_framework_entrypoints(annotation):
 marker='import org.springframework.web.bind.annotation.*; import jakarta.servlet.annotation.WebServlet;'
 r=FrameworkAwareAnalyzer().analyze_units((u(f'{marker} class A {{ @{annotation} void go(){{ String x=RequestParam("q"); statement.executeQuery(x); }} }}'),))
 assert r.taint_report.findings


def test_default_engine_catalogs_unchanged():
 engine=InterproceduralTaintAnalyzer()
 assert engine.sources==SOURCES and engine.sanitizers==SANITIZERS and engine.rules==TAINT_RULES

def test_no_framework_keeps_default_behavior():
 r=FrameworkAwareAnalyzer().analyze_units((u('class A { void go(){ String x=request.getParameter("q"); statement.executeQuery(x); } }'),),entrypoints=('go',))
 assert r.detection.frameworks==() and len(r.taint_report.findings)==1

def test_multiple_frameworks_are_sorted():
 r=FrameworkDetector().detect((u('import com.google.gson.Gson; import org.springframework.web.bind.annotation.*;'),))
 assert tuple(f.value for f in r.frameworks)==tuple(sorted(f.value for f in r.frameworks))

def test_evidence_contains_path_and_marker():
 r=FrameworkDetector().detect((u('import com.google.gson.Gson;','src/A.java'),))
 assert any('src/A.java:' in evidence for _,evidence in r.evidence)

def test_metrics_describe_active_catalog():
 r=FrameworkAwareAnalyzer().analyze_units((u('import com.google.gson.Gson; class A {}'),))
 assert r.metrics.detected_frameworks==1 and r.metrics.active_rules>len(TAINT_RULES)

def test_configurations_participate_in_detection():
 r=FrameworkDetector().detect((),(('application.properties','spring.security.user.name=admin\norg.springframework.security'),))
 assert Framework.SPRING_SECURITY in r.frameworks

def test_profiles_have_unique_frameworks():
 assert len({p.framework for p in PROFILES})==len(PROFILES)
