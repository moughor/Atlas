import json
import pytest
from dataclasses import replace
from moughorai.security_explanations import *
from moughorai.security_analysis.models import *
from moughorai.security_analysis.exporters import SecurityReportExporter
from moughorai.security_knowledge import SecurityKnowledgeBase

RULES=['ATLAS-SQL-001','ATLAS-CMD-001','ATLAS-PATH-001','ATLAS-SSRF-001','ATLAS-DESER-001','ATLAS-REFLECT-001','ATLAS-XXE-001','ATLAS-SECRET-001','ATLAS-CRYPTO-001','ATLAS-SPRING-EL-001','ATLAS-JPA-001','ATLAS-JACKSON-001']
def finding(rule='ATLAS-SQL-001',confidence=Confidence.HIGH,trace=True):
    t=(TraceStep('request parameter',SourceLocation('Controller.java',4,3)),TraceStep('service return',SourceLocation('Service.java',8,2)),TraceStep('query execution',SourceLocation('Repo.java',12,7))) if trace else ()
    return SecurityFinding(rule,'Fallback title','unsafe flow',Severity.CRITICAL,confidence,'CWE-89','A03:2021',SourceLocation('Repo.java',12,7),t,(('method','find'),))
def report(*items): return SecurityReport(tuple(items),ScanStatistics(3,len(items),len(items),0,0,0,0))

@pytest.mark.parametrize('rule',RULES)
def test_explains_every_catalog_rule(rule):
    e=SecurityExplanationEngine().explain(finding(rule)); assert e.rule_id==rule and e.impact and e.remediation_steps
@pytest.mark.parametrize('rule',RULES)
def test_taxonomy_matches_knowledge(rule):
    e=SecurityExplanationEngine().explain(finding(rule)); k=SecurityKnowledgeBase().require(rule); assert e.cwe==k.cwe and e.owasp==k.owasp and e.mitre==k.mitre
@pytest.mark.parametrize('audience',list(ExplanationAudience))
def test_audiences(audience):
    e=SecurityExplanationEngine().explain(finding(),audience); assert e.audience is audience and e.summary
@pytest.mark.parametrize('confidence',list(Confidence))
def test_confidence_reason(confidence):
    e=SecurityExplanationEngine().explain(finding(confidence=confidence)); assert e.confidence==confidence.value and e.confidence_reason
@pytest.mark.parametrize('trace_count',[0,1,3])
def test_path_roles(trace_count):
    f=finding(trace=False)
    if trace_count: f=replace(f,trace=tuple(TraceStep(f's{i}',SourceLocation('A.java',i,1)) for i in range(1,trace_count+1)))
    p=SecurityExplanationEngine().explain(f).path
    assert p[0].role in ('source','sink') and p[-1].role=='sink'
@pytest.mark.parametrize('rule',RULES[:8])
def test_serialization_is_deterministic(rule):
    engine=SecurityExplanationEngine(); a=engine.explain(finding(rule)).to_dict(); b=engine.explain(finding(rule)).to_dict(); assert a==b and json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)
@pytest.mark.parametrize('rule',RULES[:6])
def test_markdown_contains_sections(rule):
    md=SecurityExplanationEngine().explain(finding(rule)).to_markdown(); assert '**Impact:**' in md and '**Remediation**' in md and '**Evidence path**' in md

def test_unknown_rule_has_safe_fallback():
    e=SecurityExplanationEngine().explain(finding('CUSTOM-001')); assert e.rule_id=='CUSTOM-001' and e.remediation_steps and e.cwe==('CWE-89',)
def test_report_order_is_deterministic():
    a=finding('ATLAS-CMD-001'); b=replace(finding(),location=SourceLocation('A.java',1,1)); out=SecurityExplanationEngine().explain_report(report(a,b)); assert out[0].headline.endswith('A.java')
def test_provider_may_polish():
    class P:
        name='test'
        def polish(self,e): return replace(e,summary='polished')
    e=SecurityExplanationEngine(provider=P()).explain(finding()); assert e.summary=='polished' and e.generated_by.endswith('+test')
def test_bad_provider_is_rejected():
    class P:
        name='bad'
        def polish(self,e): return {'bad':True}
    with pytest.raises(TypeError): SecurityExplanationEngine(provider=P()).explain(finding())
def test_json_export_is_backward_compatible_without_engine():
    data=SecurityReportExporter().to_dict(report(finding())); assert 'explanation' not in data['findings'][0]
def test_json_export_can_include_explanation():
    engine=SecurityExplanationEngine(); data=SecurityReportExporter(engine.knowledge_base,engine).to_dict(report(finding())); assert data['findings'][0]['explanation']['rule_id']=='ATLAS-SQL-001'
def test_sarif_can_include_help():
    engine=SecurityExplanationEngine(); data=json.loads(SecurityReportExporter(engine.knowledge_base,engine).to_sarif(report(finding()))); rule=data['runs'][0]['tool']['driver']['rules'][0]; assert 'help' in rule and 'markdown' in rule['help']
def test_sarif_without_engine_unchanged_shape():
    data=json.loads(SecurityReportExporter().to_sarif(report(finding()))); assert 'help' not in data['runs'][0]['tool']['driver']['rules'][0]
def test_missing_trace_uses_finding_location():
    e=SecurityExplanationEngine().explain(finding(trace=False)); assert e.path[0].path=='Repo.java' and e.path[0].line==12
def test_locationless_last_trace_is_completed():
    f=replace(finding(),trace=(TraceStep('source',SourceLocation('A.java',1,1)),TraceStep('sink'))); e=SecurityExplanationEngine().explain(f); assert e.path[-1].path=='Repo.java'
def test_string_audience_is_accepted(): assert SecurityExplanationEngine().explain(finding(),'security').audience is ExplanationAudience.SECURITY
def test_invalid_audience_rejected():
    with pytest.raises(ValueError): SecurityExplanationEngine().explain(finding(),'invalid')
def test_explanation_is_immutable():
    e=SecurityExplanationEngine().explain(finding())
    with pytest.raises(Exception): e.summary='changed'
def test_reference_metadata_present(): assert SecurityExplanationEngine().explain(finding()).references
def test_examples_present_for_known_rule():
    e=SecurityExplanationEngine().explain(finding()); assert e.safe_example and e.unsafe_example
def test_fingerprint_preserved():
    f=finding(); assert SecurityExplanationEngine().explain(f).fingerprint==f.fingerprint
def test_evidence_indexes_are_one_based(): assert [s.index for s in SecurityExplanationEngine().explain(finding()).path]==[1,2,3]
def test_engine_version(): assert SecurityExplanationEngine.VERSION=='1.0'
