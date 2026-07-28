import json
from pathlib import Path
import pytest
from moughorai.java_security import JavaSecurityAnalyzer
from moughorai.security_analysis import Severity
from moughorai.security_ci import *

def report(src='String x=request.getParameter("x"); Runtime.getRuntime().exec(x);', path='src/App.java'):
    return JavaSecurityAnalyzer().analyze_source(src,path)

def test_default_gate_fails_high_new():
    r=SecurityQualityGate().evaluate(report())
    assert r.status is GateStatus.FAIL and r.exit_code==1 and r.new_count==1

def test_baseline_makes_existing_pass():
    rep=report(); base=SecurityBaseline.from_report(rep)
    r=SecurityQualityGate().evaluate(rep,baseline=base)
    assert r.status is GateStatus.PASS and r.existing_count==1

def test_fail_on_all_includes_baseline():
    rep=report(); p=ScanPolicy(fail_on_new_only=False)
    assert SecurityQualityGate().evaluate(rep,p,SecurityBaseline.from_report(rep)).status is GateStatus.FAIL

@pytest.mark.parametrize('severity,expected',[('critical','fail'),('high','fail'),('medium','fail'),('low','fail'),('info','fail')])
def test_severity_thresholds(severity,expected):
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(minimum_severity=Severity(severity)))
    assert r.status.value==expected

@pytest.mark.parametrize('rule', ['ATLAS-CMD-001','ATLAS-SQL-001','ATLAS-PATH-001'])
def test_enabled_rule_filter(rule):
    src='String x=request.getParameter("x"); Runtime.getRuntime().exec(x);'
    r=SecurityQualityGate().evaluate(report(src),ScanPolicy(enabled_rules=(rule,)))
    assert (r.status is GateStatus.FAIL)==(rule=='ATLAS-CMD-001')

def test_disabled_rule_filter():
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(disabled_rules=('ATLAS-CMD-001',)))
    assert r.status is GateStatus.PASS and len(r.ignored)==1

def test_rule_overlap_rejected():
    with pytest.raises(ValueError): ScanPolicy(enabled_rules=('A',),disabled_rules=('A',))

def test_negative_budget_rejected():
    with pytest.raises(ValueError): ScanPolicy(max_findings=-1)

def test_exact_suppression():
    s=Suppression('ATLAS-CMD-001','src/*','accepted risk')
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(suppressions=(s,)))
    assert r.status is GateStatus.PASS and r.suppressed_count==1 and r.ignored[0].suppression_reason=='accepted risk'

def test_fingerprint_suppression():
    rep=report(); f=rep.findings[0]
    s=Suppression(fingerprint=f.fingerprint)
    assert SecurityQualityGate().evaluate(rep,ScanPolicy(suppressions=(s,))).suppressed_count==1

def test_wrong_fingerprint_does_not_suppress():
    s=Suppression(fingerprint='other')
    assert SecurityQualityGate().evaluate(report(),ScanPolicy(suppressions=(s,))).status is GateStatus.FAIL

@pytest.mark.parametrize('pattern,passed',[('src/*',False),('test/*',True),('*',False)])
def test_include_paths(pattern,passed):
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(include_paths=(pattern,)))
    assert (r.status is GateStatus.PASS)==passed

def test_exclude_paths():
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(exclude_paths=('src/*',)))
    assert r.status is GateStatus.PASS

def test_budget_fails_below_threshold():
    low=report('String password = "password=supersecret123";')
    r=SecurityQualityGate().evaluate(low,ScanPolicy(minimum_severity=Severity.CRITICAL,max_findings=0))
    assert r.status is GateStatus.FAIL

def test_budget_passes_equal():
    low=report('String password = "password=supersecret123";')
    r=SecurityQualityGate().evaluate(low,ScanPolicy(minimum_severity=Severity.CRITICAL,max_findings=1))
    assert r.status is GateStatus.PASS

def test_baseline_json_roundtrip():
    b=SecurityBaseline.from_report(report()); assert SecurityBaseline.from_json(b.to_json())==b

def test_baseline_sorted():
    b=SecurityBaseline(frozenset({'z','a'})); assert list(json.loads(b.to_json())['fingerprints'])==['a','z']

def test_baseline_invalid():
    with pytest.raises(ValueError): SecurityBaseline.from_dict({'fingerprints':'x'})

def test_baseline_file(tmp_path):
    p=tmp_path/'base.json'; b=SecurityBaseline.from_report(report()); b.save(p); assert SecurityBaseline.load(p)==b

def test_policy_json_defaults():
    p=PolicyLoader.from_json('{}'); assert p.minimum_severity is Severity.HIGH

def test_policy_json_full():
    p=PolicyLoader.from_dict({'minimum_severity':'medium','disabled_rules':['X'],'fail_on_new_only':False,'max_findings':3,'include_paths':['src/*'],'exclude_paths':['src/test/*'],'suppressions':[{'rule_id':'R','path_pattern':'a/*','reason':'ok'}]})
    assert p.minimum_severity is Severity.MEDIUM and p.max_findings==3 and p.suppressions[0].reason=='ok'

def test_policy_invalid_severity():
    with pytest.raises(ValueError): PolicyLoader.from_dict({'minimum_severity':'extreme'})

def test_policy_invalid_root():
    with pytest.raises(ValueError): PolicyLoader.from_dict([])

def test_policy_invalid_suppression():
    with pytest.raises(ValueError): PolicyLoader.from_dict({'suppressions':['x']})

def test_policy_load_json(tmp_path):
    p=tmp_path/'atlas-security.json'; p.write_text('{"minimum_severity":"critical"}')
    assert PolicyLoader.load(p).minimum_severity is Severity.CRITICAL

def test_repository_scanner(tmp_path):
    p=tmp_path/'src/main/java/App.java'; p.parent.mkdir(parents=True); p.write_text('String x=request.getParameter("x"); Runtime.getRuntime().exec(x);')
    r=RepositorySecurityScanner().scan(tmp_path)
    assert r.status is GateStatus.FAIL and r.report.findings[0].location.path=='src/main/java/App.java'

def test_repository_scanner_config(tmp_path):
    p=tmp_path/'src/main/resources/application.properties'; p.parent.mkdir(parents=True); p.write_text('server.ssl.enabled=false')
    r=RepositorySecurityScanner().scan(tmp_path,ScanPolicy(minimum_severity=Severity.MEDIUM))
    assert r.report.findings

def test_repository_ignores_target(tmp_path):
    p=tmp_path/'target/App.java'; p.parent.mkdir(); p.write_text('String x=request.getParameter("x"); Runtime.getRuntime().exec(x);')
    assert not RepositorySecurityScanner().scan(tmp_path).report.findings

def test_write_json(tmp_path):
    out=tmp_path/'out.json'; r=SecurityQualityGate().evaluate(report()); RepositorySecurityScanner.write_outputs(r,json_path=out)
    assert json.loads(out.read_text())['findings'][0]['rule_id']=='ATLAS-CMD-001'

def test_write_sarif(tmp_path):
    out=tmp_path/'out.sarif'; r=SecurityQualityGate().evaluate(report()); RepositorySecurityScanner.write_outputs(r,sarif_path=out)
    assert json.loads(out.read_text())['version']=='2.1.0'

def test_write_baseline(tmp_path):
    out=tmp_path/'base.json'; r=SecurityQualityGate().evaluate(report()); RepositorySecurityScanner.write_outputs(r,baseline_path=out)
    assert SecurityBaseline.load(out).fingerprints

def test_deterministic_message():
    assert SecurityQualityGate().evaluate(report()).message.startswith('fail: 1 finding(s)')

def test_filtered_statistics():
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(disabled_rules=('ATLAS-CMD-001',)))
    assert r.report.statistics.finding_count==0

def test_multiple_findings_counts():
    rep=JavaSecurityAnalyzer().analyze_source('String x=request.getParameter("x"); Runtime.getRuntime().exec(x); statement.executeQuery(x);','src/App.java')
    r=SecurityQualityGate().evaluate(rep)
    assert r.new_count==2 and r.threshold_count==2

def test_suppression_wildcard():
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(suppressions=(Suppression(),)))
    assert r.status is GateStatus.PASS

def test_suppression_rule_mismatch():
    r=SecurityQualityGate().evaluate(report(),ScanPolicy(suppressions=(Suppression('OTHER'),)))
    assert r.status is GateStatus.FAIL

def test_scan_with_policy_and_baseline_files(tmp_path):
    src=tmp_path/'App.java'; src.write_text('String x=request.getParameter("x"); Runtime.getRuntime().exec(x);')
    pol=tmp_path/'policy.json'; pol.write_text('{"minimum_severity":"high"}')
    first=RepositorySecurityScanner().scan(tmp_path); base=tmp_path/'base.json'; SecurityBaseline.from_report(first.report).save(base)
    assert RepositorySecurityScanner().scan_with_files(tmp_path,pol,base).status is GateStatus.PASS

@pytest.mark.parametrize('value',[True,False])
def test_policy_boolean(value):
    p=PolicyLoader.from_dict({'fail_on_new_only':value}); assert p.fail_on_new_only is value

@pytest.mark.parametrize('path',['src/A.java','module/src/B.java','A.java'])
def test_path_storage(path):
    assert report(path=path).findings[0].location.path==path
