import pytest
from moughorai.dataflow import FlowNode,FlowPath,FlowRole,MethodId
from moughorai.security_analysis.models import Confidence,Severity,SourceLocation
from moughorai.taint_policy import *

def node(symbol,role,line=1,msg=''):
    return FlowNode(MethodId('Demo','run',0),symbol,role,SourceLocation('Demo.java',line,1),msg)
def path(source='requestParam',middle=('value',),sink='executeQuery',truncated=False,recursion=False):
    nodes=[node(source,FlowRole.SOURCE,1,'source')]
    nodes += [node(x,FlowRole.PROPAGATION,i+2,x) for i,x in enumerate(middle)]
    nodes += [node(sink,FlowRole.SINK,len(middle)+2,'sink')]
    return FlowPath(tuple(nodes),truncated,recursion)
def policy(**kw):
    base=dict(rule_id='R1',title='Title',message='Message',sources=(SymbolMatcher('request',MatchMode.CONTAINS),),sinks=(SymbolMatcher('execute',MatchMode.CONTAINS),))
    base.update(kw); return TaintPolicy(**base)

@pytest.mark.parametrize('mode,value,pattern,expected',[
    (MatchMode.EXACT,'abc','abc',True),(MatchMode.EXACT,'abcd','abc',False),
    (MatchMode.PREFIX,'abcdef','abc',True),(MatchMode.PREFIX,'zabc','abc',False),
    (MatchMode.SUFFIX,'abcdef','def',True),(MatchMode.SUFFIX,'defz','def',False),
    (MatchMode.CONTAINS,'abcdef','cd',True),(MatchMode.CONTAINS,'abcdef','zz',False)])
def test_match_modes(mode,value,pattern,expected): assert SymbolMatcher(pattern,mode).matches(value) is expected

def test_empty_matcher_rejected():
    with pytest.raises(ValueError): SymbolMatcher(' ')
@pytest.mark.parametrize('field', ['rule_id','title'])
def test_required_policy_text(field):
    args={field:' '}
    with pytest.raises(ValueError): policy(**args)
def test_sources_required():
    with pytest.raises(ValueError): policy(sources=())
def test_sinks_required():
    with pytest.raises(ValueError): policy(sinks=())
def test_priority_nonnegative():
    with pytest.raises(ValueError): policy(priority=-1)
def test_duplicate_policy_rejected():
    with pytest.raises(ValueError): TaintPolicyEngine((policy(),policy()))
def test_policy_order_is_deterministic():
    a=policy(rule_id='B',priority=20); b=policy(rule_id='A',priority=20); c=policy(rule_id='C',priority=10)
    assert [p.rule_id for p in TaintPolicyEngine((a,b,c)).policies]==['C','A','B']
def test_match():
    d=TaintPolicyEngine().evaluate(path(),policy()); assert d.matched and not d.sanitized
def test_source_miss():
    d=TaintPolicyEngine().evaluate(path(source='constant'),policy()); assert not d.matched and 'source' in d.reason
def test_sink_miss():
    d=TaintPolicyEngine().evaluate(path(sink='logger'),policy()); assert not d.matched and 'sink' in d.reason
def test_disabled():
    d=TaintPolicyEngine().evaluate(path(),policy(enabled=False)); assert not d.matched and d.reason=='policy disabled'
def test_empty_path():
    d=TaintPolicyEngine().evaluate(FlowPath(()),policy()); assert not d.matched and d.reason=='empty path'
def test_sanitizer_suppresses():
    p=policy(sanitizers=(SymbolMatcher('clean'),)); d=TaintPolicyEngine().evaluate(path(middle=('clean',)),p)
    assert d.sanitized and not d.matched and d.sanitizer_symbol=='clean'
def test_endpoint_named_like_sanitizer_does_not_suppress():
    p=policy(sanitizers=(SymbolMatcher('requestParam'),)); assert TaintPolicyEngine().evaluate(path(),p).matched
def test_decisions_cross_product():
    ps=(policy(rule_id='A'),policy(rule_id='B')); assert len(TaintPolicyEngine(ps).decisions((path(),path(sink='logger'))))==4
def test_finding_fields():
    f=TaintPolicyEngine((policy(severity=Severity.CRITICAL,confidence=Confidence.MEDIUM,cwe='CWE-89',owasp='A03'),)).findings((path(),))[0]
    assert (f.rule_id,f.severity,f.confidence,f.cwe,f.owasp)==('R1',Severity.CRITICAL,Confidence.MEDIUM,'CWE-89','A03')
def test_finding_preserves_trace():
    f=TaintPolicyEngine((policy(),)).findings((path(middle=('a','b')),))[0]; assert [x.message for x in f.trace]==['source','a','b','sink']
def test_finding_properties():
    f=TaintPolicyEngine((policy(priority=7,properties=(('team','appsec'),)),)).findings((path(truncated=True,recursion=True),))[0]; p=dict(f.properties)
    assert p['team']=='appsec' and p['policy_priority']=='7' and p['dataflow_truncated']=='true' and p['dataflow_recursion']=='true'
def test_unmatched_has_no_finding(): assert TaintPolicyEngine((policy(),)).findings((path(source='safe'),))==()
def test_missing_locations_skip_finding():
    m=MethodId('','x',0); pth=FlowPath((FlowNode(m,'request',FlowRole.SOURCE),FlowNode(m,'execute',FlowRole.SINK)))
    assert TaintPolicyEngine((policy(),)).findings((pth,))==()
def test_finding_deduplicates_by_fingerprint():
    assert len(TaintPolicyEngine((policy(),)).findings((path(),path())))==1
def test_report_statistics():
    ps=(policy(rule_id='C',severity=Severity.CRITICAL),policy(rule_id='H',severity=Severity.HIGH),policy(rule_id='M',severity=Severity.MEDIUM),policy(rule_id='L',severity=Severity.LOW),policy(rule_id='I',severity=Severity.INFO))
    r=TaintPolicyEngine(ps).report((path(),),('warning',)); s=r.statistics
    assert (s.rule_count,s.finding_count,s.critical,s.high,s.medium,s.low,s.info)==(5,5,1,1,1,1,1) and r.warnings==('warning',)
def test_decision_serialization():
    d=TaintPolicyEngine().evaluate(path(),policy()); assert d.to_dict()['source_symbol']=='requestParam'
def test_property_map(): assert policy(properties=(('a','b'),)).property_map=={'a':'b'}
def test_version(): assert TaintPolicyEngine.VERSION=='1.0'
@pytest.mark.parametrize('rule', ['ATLAS-POLICY-SQL-001','ATLAS-POLICY-CMD-001','ATLAS-POLICY-PATH-001'])
def test_default_catalog_rule_ids(rule): assert rule in {p.rule_id for p in default_policies()}
def test_sql_default_matches():
    fs=TaintPolicyEngine(default_policies()).findings((path(),)); assert any(f.rule_id=='ATLAS-POLICY-SQL-001' for f in fs)
def test_sql_default_sanitized():
    fs=TaintPolicyEngine(default_policies()).findings((path(middle=('sanitizeSql',)),)); assert all(f.rule_id!='ATLAS-POLICY-SQL-001' for f in fs)
@pytest.mark.parametrize('n',range(20))
def test_deterministic_repeated_runs(n):
    e=TaintPolicyEngine((policy(),)); assert e.findings((path(),))==e.findings((path(),))
