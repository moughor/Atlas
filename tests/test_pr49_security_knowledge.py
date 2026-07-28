import json
import pytest
from moughorai.security_knowledge import *
from moughorai.security_analysis.exporters import SecurityReportExporter
from moughorai.security_analysis.models import *

RULES=['ATLAS-SQL-001','ATLAS-CMD-001','ATLAS-PATH-001','ATLAS-SSRF-001','ATLAS-DESER-001','ATLAS-REFLECT-001','ATLAS-XXE-001','ATLAS-SECRET-001','ATLAS-CRYPTO-001','ATLAS-SPRING-EL-001','ATLAS-JPA-001','ATLAS-JACKSON-001']

def finding(rule='ATLAS-SQL-001'):
    return SecurityFinding(rule,'SQL injection','bad',Severity.CRITICAL,Confidence.HIGH,'CWE-89','A03:2021',SourceLocation('A.java',3,4))
def report(rule='ATLAS-SQL-001'):
    return SecurityReport((finding(rule),),ScanStatistics(1,1,1,0,0,0,0))

@pytest.mark.parametrize('rule',RULES)
def test_catalog_lookup(rule):
    e=SecurityKnowledgeBase().require(rule); assert e.rule_id==rule and e.references

@pytest.mark.parametrize('rule',RULES)
def test_catalog_entries_have_complete_metadata(rule):
    e=SecurityKnowledgeBase().require(rule)
    assert e.cwe and e.owasp and e.mitre and e.cvss_vector and e.remediation.steps

@pytest.mark.parametrize('score,expected',[(0,'none'),(.1,'low'),(3.9,'low'),(4,'medium'),(6.9,'medium'),(7,'high'),(8.9,'high'),(9,'critical'),(10,'critical')])
def test_cvss_severity(score,expected):
    e=SecurityKnowledge('X','x','x',(),(),(),score,'CVSS:3.1/AV:N',Remediation('x'))
    assert e.cvss_severity==expected

def test_sorted_iteration(): assert [e.rule_id for e in SecurityKnowledgeBase()]==sorted(RULES)
def test_unknown_get(): assert SecurityKnowledgeBase().get('NOPE') is None
def test_unknown_require():
    with pytest.raises(KeyError,match='unknown security rule'): SecurityKnowledgeBase().require('NOPE')
def test_duplicate_rejected():
    e=SecurityKnowledgeBase().require(RULES[0])
    with pytest.raises(ValueError,match='duplicate'): SecurityKnowledgeBase((e,e))
def test_bad_score():
    with pytest.raises(ValueError): SecurityKnowledge('X','x','x',(),(),(),11,'CVSS:3.1/X',Remediation('x'))
def test_bad_vector():
    with pytest.raises(ValueError): SecurityKnowledge('X','x','x',(),(),(),1,'CVSS:4.0/X',Remediation('x'))
def test_search_text(): assert SecurityKnowledgeBase().search('database')
def test_search_cwe(): assert {e.rule_id for e in SecurityKnowledgeBase().search(cwe='CWE-89')}=={'ATLAS-SQL-001','ATLAS-JPA-001'}
def test_search_owasp(): assert SecurityKnowledgeBase().search(owasp='A10:2021')[0].rule_id=='ATLAS-SSRF-001'
def test_search_mitre(): assert SecurityKnowledgeBase().search(mitre='T1059')
def test_search_tag_case_insensitive(): assert SecurityKnowledgeBase().search(tag='DATABASE')
def test_search_combined_filter(): assert [e.rule_id for e in SecurityKnowledgeBase().search('query',cwe='CWE-89')]==['ATLAS-JPA-001','ATLAS-SQL-001']
def test_to_dict_deterministic():
    kb=SecurityKnowledgeBase(); assert kb.to_dict()==kb.to_dict()
def test_to_dict_json_serializable(): json.dumps(SecurityKnowledgeBase().to_dict(),sort_keys=True)
def test_coverage_complete():
    c=SecurityKnowledgeBase().coverage(RULES); assert c['coverage']==1 and not c['missing_rule_ids']
def test_coverage_partial():
    c=SecurityKnowledgeBase().coverage(['ATLAS-SQL-001','X']); assert c['coverage']==.5 and c['missing_rule_ids']==('X',)
def test_coverage_empty(): assert SecurityKnowledgeBase().coverage([])['coverage']==1
def test_enrich_known(): assert 'knowledge' in SecurityKnowledgeBase().enrich_dict({'rule_id':'ATLAS-SQL-001'})
def test_enrich_unknown_preserves(): assert SecurityKnowledgeBase().enrich_dict({'rule_id':'X','a':1})=={'rule_id':'X','a':1}
def test_exporter_without_kb_backward_compatible(): assert 'knowledge' not in SecurityReportExporter().to_dict(report())['findings'][0]
def test_exporter_with_kb_enriches_json():
    d=SecurityReportExporter(SecurityKnowledgeBase()).to_dict(report()); assert d['findings'][0]['knowledge']['cvss']['score']==9.8
def test_exporter_json_deterministic():
    e=SecurityReportExporter(SecurityKnowledgeBase()); assert e.to_json(report())==e.to_json(report())
def test_sarif_enriched_score_and_vector():
    d=json.loads(SecurityReportExporter(SecurityKnowledgeBase()).to_sarif(report()))
    p=d['runs'][0]['tool']['driver']['rules'][0]['properties']; assert p['security-severity']=='9.8' and p['cvss-vector'].startswith('CVSS:3.1/')
def test_sarif_enriched_tags_include_mitre():
    d=json.loads(SecurityReportExporter(SecurityKnowledgeBase()).to_sarif(report('ATLAS-CMD-001')))
    assert 'T1059' in d['runs'][0]['tool']['driver']['rules'][0]['properties']['tags']
def test_reference_kinds_are_serialized():
    d=SecurityKnowledgeBase().require('ATLAS-SQL-001').to_dict(); assert {r['kind'] for r in d['references']}=={'cwe','owasp'}
def test_examples_are_present():
    r=SecurityKnowledgeBase().require('ATLAS-SQL-001').remediation; assert 'PreparedStatement' in r.safe_example and 'executeQuery' in r.unsafe_example
def test_version_present(): assert SecurityKnowledgeBase().to_dict()['knowledge_version']=='1.0'
def test_empty_rule_id_rejected():
    with pytest.raises(ValueError): SecurityKnowledge(' ','x','x',(),(),(),1,'CVSS:3.1/X',Remediation('x'))
