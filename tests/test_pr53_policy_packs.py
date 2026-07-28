import json
import pytest
from moughorai.policy_packs import *
from moughorai.security_analysis.models import Confidence,Severity
from moughorai.taint_policy import MatchMode

YAML='''schema_version: 1
name: web
version: 1.2.0
description: Web rules
metadata:
  owner: appsec
policies:
  - rule_id: WEB-SQL
    title: SQL flow
    message: Unsafe SQL
    sources:
      - pattern: request
        mode: contains
    sinks: [execute]
    sanitizers: [prepared]
    severity: critical
    confidence: medium
    cwe: CWE-89
    owasp: A03:2021
    priority: 5
    properties:
      team: security
'''
def load(text=YAML): return PolicyPackLoader().load_yaml(text)
def test_load_yaml_fields():
    p=load(); assert (p.name,p.version,p.schema_version,p.description)==('web','1.2.0',1,'Web rules')
def test_policy_fields():
    p=load().policies[0]; assert (p.rule_id,p.severity,p.confidence,p.priority)==('WEB-SQL',Severity.CRITICAL,Confidence.MEDIUM,5)
def test_matcher_forms():
    p=load().policies[0]; assert p.sources[0].mode is MatchMode.CONTAINS and p.sinks[0].mode is MatchMode.EXACT
def test_metadata_and_properties(): assert load().metadata_map=={'owner':'appsec'} and load().policies[0].property_map=={'team':'security'}
def test_load_json(): assert PolicyPackLoader().load_json(json.dumps(pack_to_dict(load())))==load()
def test_roundtrip_yaml(): assert PolicyPackLoader().load_yaml(pack_to_yaml(load()))==load()
def test_roundtrip_json(): assert PolicyPackLoader().load_json(pack_to_json(load()))==load()
def test_json_deterministic(): assert pack_to_json(load())==pack_to_json(load())
def test_empty_pack_warning():
    p=PolicyPackLoader().load_yaml('name: empty\nversion: 1\npolicies: []\n'); assert p.diagnostics[0].code=='empty-pack'
def test_registry_order():
    p=load(); q=PolicyPack('aaa','1',(p.policies[0].__class__('A','A','A',p.policies[0].sources,p.policies[0].sinks,priority=20),))
    assert [x.rule_id for x in PolicyPackRegistry((p,q)).policies()]==['WEB-SQL','A']
def test_override():
    o=PolicyOverride('WEB-SQL',enabled=False,priority=99,severity='low',confidence='high',properties=(('owner','platform'),))
    p=PolicyPackRegistry((load(),)).policies((o,))[0]; assert not p.enabled and p.priority==99 and p.severity is Severity.LOW and p.confidence is Confidence.HIGH and p.property_map['owner']=='platform'
def test_registry_engine(): assert len(PolicyPackRegistry((load(),)).engine().policies)==1
def test_diagnostics_aggregate():
    p=PolicyPackLoader().load_yaml('name: empty\nversion: 1\npolicies: []\n'); assert len(PolicyPackRegistry((p,)).diagnostics())==1
@pytest.mark.parametrize('text,part',[
 ('[]','root must be a mapping'),
 ('name: x\nversion: 1\nextra: true','unknown root fields'),
 ('schema_version: x\nname: x\nversion: 1','schema_version must be an integer'),
 ('schema_version: 2\nname: x\nversion: 1','unsupported schema_version'),
 ('name: ""\nversion: 1','pack name'),
 ('name: x\nversion: ""','pack version'),
 ('name: x\nversion: 1\npolicies: {}','policies must be a list'),
 ('name: x\nversion: 1\nmetadata: []','metadata: must be a mapping'),
])
def test_invalid_roots(text,part):
    with pytest.raises(PolicyPackError,match=part): load(text)
@pytest.mark.parametrize('fragment,part',[
 ('unknown: x','unknown policy fields'),('sources: x','sources: must be a list'),('sources: []','sources: must not be empty'),('sinks: x','sinks: must be a list'),('sinks: []','sinks: must not be empty'),('severity: nope','severity: invalid value'),('confidence: nope','confidence: invalid value'),('priority: x','priority: must be an integer'),('enabled: x','enabled: must be a boolean'),('properties: []','properties: must be a mapping')])
def test_invalid_policy(fragment,part):
    text='''name: x\nversion: 1\npolicies:\n  - rule_id: R\n    title: T\n    message: M\n    sources: [s]\n    sinks: [k]\n'''+''.join('    '+line+'\n' for line in fragment.splitlines())
    with pytest.raises(PolicyPackError,match=part): load(text)
@pytest.mark.parametrize('matcher,part',[
 ('42','matcher must be a string or mapping'),('{pattern: x, extra: y}','unknown matcher fields'),('{pattern: x, mode: nope}','mode: invalid value'),('{pattern: ""}','pattern must not be empty')])
def test_invalid_matcher(matcher,part):
    text=f'''name: x\nversion: 1\npolicies:\n  - rule_id: R\n    title: T\n    message: M\n    sources: [{matcher}]\n    sinks: [k]\n'''
    with pytest.raises((PolicyPackError,ValueError),match=part): load(text)
def test_duplicate_pack_name():
    with pytest.raises(PolicyPackError,match='duplicate policy pack name'): PolicyPackRegistry((load(),load()))
def test_duplicate_rule_across_packs():
    a=load(); b=PolicyPack('other','1',a.policies)
    with pytest.raises(PolicyPackError,match='across packs'): PolicyPackRegistry((a,b)).policies()
def test_unknown_override_strict():
    with pytest.raises(PolicyPackError,match='unknown rule_id'): PolicyPackRegistry((load(),)).policies((PolicyOverride('NOPE'),))
def test_unknown_override_non_strict(): assert len(PolicyPackRegistry((load(),)).policies((PolicyOverride('NOPE'),),False))==1
@pytest.mark.parametrize('field,value', [('severity','bad'),('confidence','bad')])
def test_bad_override_enum(field,value):
    with pytest.raises(PolicyPackError,match='invalid override'): PolicyPackRegistry((load(),)).policies((PolicyOverride('WEB-SQL',**{field:value}),))
def test_negative_override_priority():
    with pytest.raises(PolicyPackError): PolicyOverride('R',priority=-1)
def test_empty_override_id():
    with pytest.raises(PolicyPackError): PolicyOverride(' ')
def test_duplicate_policy_in_pack():
    p=load().policies[0]
    with pytest.raises(PolicyPackError,match='duplicate policy'): PolicyPack('x','1',(p,p))
def test_unsupported_extension(tmp_path):
    f=tmp_path/'pack.txt'; f.write_text(YAML)
    with pytest.raises(PolicyPackError,match='unsupported'): PolicyPackLoader().load_file(f)
def test_load_file_yaml(tmp_path):
    f=tmp_path/'pack.yaml'; f.write_text(YAML); assert PolicyPackLoader().load_file(f).name=='web'
def test_load_file_json(tmp_path):
    f=tmp_path/'pack.json'; f.write_text(pack_to_json(load())); assert PolicyPackLoader().load_file(f).name=='web'
def test_missing_file(tmp_path):
    with pytest.raises(PolicyPackError,match='cannot read'): PolicyPackLoader().load_file(tmp_path/'missing.yaml')
def test_invalid_yaml():
    with pytest.raises(PolicyPackError,match='invalid YAML'): load('name: [')
def test_invalid_json():
    with pytest.raises(PolicyPackError,match='invalid JSON'): PolicyPackLoader().load_json('{')
def test_diagnostic_serialization(): assert PolicyPackDiagnostic('warning','x','m','p').to_dict()['code']=='x'
def test_schema_constant(): assert PolicyPackLoader.SCHEMA_VERSION==1
@pytest.mark.parametrize('n',range(15))
def test_deterministic_repeated(n): assert pack_to_dict(load())==pack_to_dict(load())
