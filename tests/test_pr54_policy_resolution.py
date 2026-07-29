import json
import pytest
from moughorai.policy_packs import *


def pack(name,version='1.0.0',deps=()): return PolicyPack(name,version,(),dependencies=tuple(deps))

@pytest.mark.parametrize('value,parts',[
 ('0.0.0',(0,0,0,'')),('1.2.3',(1,2,3,'')),('10.20.30',(10,20,30,'')),('1.0.0-alpha',(1,0,0,'alpha'))])
def test_semver_parse(value,parts):
    v=SemanticVersion.parse(value); assert (v.major,v.minor,v.patch,v.prerelease)==parts and str(v)==value
@pytest.mark.parametrize('value',['1','1.2','v1.2.3','01.2.3','1.02.3','1.2.03','','x'])
def test_invalid_semver(value):
    with pytest.raises(PolicyPackError,match='invalid semantic version'): SemanticVersion.parse(value)
@pytest.mark.parametrize('constraint,version,expected',[
 ('*','9.9.9',True),('1.2.3','1.2.3',True),('1.2.3','1.2.4',False),('==1.2.3','1.2.3',True),
 ('>=1.2.0','1.2.0',True),('>=1.2.0','1.1.9',False),('>1.2.0','1.2.1',True),('>1.2.0','1.2.0',False),
 ('<=2.0.0','2.0.0',True),('<2.0.0','2.0.0',False),('>=1.0.0,<2.0.0','1.9.9',True),
 ('^1.2.3','1.9.0',True),('^1.2.3','2.0.0',False),('^0.2.3','0.2.9',True),('^0.2.3','0.3.0',False),
 ('^0.0.3','0.0.3',True),('^0.0.3','0.0.4',False),('~1.2.3','1.2.9',True),('~1.2.3','1.3.0',False)])
def test_constraints(constraint,version,expected): assert VersionConstraint(constraint).matches(version) is expected
@pytest.mark.parametrize('constraint',['wat','^1','~1.2','>=x'])
def test_invalid_constraint(constraint):
    with pytest.raises(PolicyPackError): VersionConstraint(constraint)
def test_dependency_validation():
    with pytest.raises(PolicyPackError): PackDependency(' ')
def test_dependency_defaults(): assert PackDependency('core').constraint=='*' and not PackDependency('core').optional
def test_resolve_dependency_first():
    core=pack('core'); web=pack('web',deps=(PackDependency('core','^1.0.0'),))
    assert [p.name for p in PolicyPackResolver((web,core)).resolve(('web',))]==['core','web']
def test_resolve_deterministic_roots():
    assert [p.name for p in PolicyPackResolver((pack('b'),pack('a'))).resolve()]==['a','b']
def test_transitive_resolution():
    a=pack('a'); b=pack('b',deps=(PackDependency('a'),)); c=pack('c',deps=(PackDependency('b'),))
    assert [p.name for p in PolicyPackResolver((c,b,a)).resolve(('c',))]==['a','b','c']
def test_shared_dependency_once():
    core=pack('core'); a=pack('a',deps=(PackDependency('core'),)); b=pack('b',deps=(PackDependency('core'),))
    assert [p.name for p in PolicyPackResolver((a,b,core)).resolve(('a','b'))]==['core','a','b']
def test_missing_root():
    with pytest.raises(PolicyPackError,match='missing policy pack dependency'): PolicyPackResolver(()).resolve(('x',))
def test_missing_required_dependency():
    with pytest.raises(PolicyPackError,match='requires missing pack'): PolicyPackResolver((pack('a',deps=(PackDependency('x'),)),)).resolve()
def test_missing_optional_dependency():
    assert [p.name for p in PolicyPackResolver((pack('a',deps=(PackDependency('x',optional=True),)),)).resolve()]==['a']
def test_version_conflict():
    a=pack('a',deps=(PackDependency('core','^2.0.0'),)); core=pack('core','1.5.0')
    with pytest.raises(PolicyPackError,match='found 1.5.0'): PolicyPackResolver((a,core)).resolve()
def test_direct_cycle():
    a=pack('a',deps=(PackDependency('b'),)); b=pack('b',deps=(PackDependency('a'),))
    with pytest.raises(PolicyPackError,match='cycle'): PolicyPackResolver((a,b)).resolve()
def test_self_cycle():
    a=pack('a',deps=(PackDependency('a'),))
    with pytest.raises(PolicyPackError,match='a -> a'): PolicyPackResolver((a,)).resolve()
def test_duplicate_pack_name_resolver():
    with pytest.raises(PolicyPackError,match='duplicate'): PolicyPackResolver((pack('a'),pack('a')))
def test_digest_deterministic(): assert pack_digest(pack('a'))==pack_digest(pack('a')) and len(pack_digest(pack('a')))==64
def test_digest_changes_version(): assert pack_digest(pack('a','1.0.0'))!=pack_digest(pack('a','1.0.1'))
def test_lock_order_and_content():
    core=pack('core'); web=pack('web',deps=(PackDependency('core'),)); lock=PolicyPackResolver((web,core)).lock(('web',))
    assert [p.name for p in lock.packs]==['core','web'] and lock.packs[1].dependencies[0].name=='core'
def test_lock_json_roundtrip():
    lock=PolicyPackResolver((pack('a'),)).lock(); assert PolicyPackLock.from_json(lock.to_json())==lock
def test_lock_json_deterministic():
    lock=PolicyPackResolver((pack('a'),)).lock(); assert lock.to_json()==lock.to_json()
def test_lock_verify():
    r=PolicyPackResolver((pack('a'),)); assert r.verify(r.lock())
def test_lock_verify_detects_change():
    lock=PolicyPackResolver((pack('a','1.0.0'),)).lock()
    with pytest.raises(PolicyPackError,match='does not match'): PolicyPackResolver((pack('a','1.0.1'),)).verify(lock)
def test_bad_lock_json():
    with pytest.raises(PolicyPackError,match='invalid lockfile'): PolicyPackLock.from_json('{')
def test_bad_lock_version():
    with pytest.raises(PolicyPackError,match='unsupported lockfile'): PolicyPackLock.from_json('{"format_version":2,"packs":[]}')
def test_loader_dependencies():
    p=PolicyPackLoader().load_yaml('name: web\nversion: 1.0.0\ndependencies:\n - name: core\n   constraint: ^1.0.0\npolicies: []\n')
    assert p.dependencies==(PackDependency('core','^1.0.0'),)
def test_loader_string_dependency():
    p=PolicyPackLoader().load_yaml('name: web\nversion: 1.0.0\ndependencies: [core]\npolicies: []\n'); assert p.dependencies[0].name=='core'
def test_dependency_roundtrip_yaml():
    p=pack('web',deps=(PackDependency('core','~1.2.0',True),)); q=PolicyPackLoader().load_yaml(pack_to_yaml(p)); assert q.name==p.name and q.version==p.version and q.dependencies==p.dependencies
@pytest.mark.parametrize('fragment,part',[
 ('dependencies: {}','dependencies must be a list'),('dependencies: [42]','dependency must be a string or mapping'),
 ('dependencies: [{name: core, extra: x}]','unknown dependency fields'),('dependencies: [{name: core, optional: x}]','optional: must be a boolean')])
def test_invalid_dependencies(fragment,part):
    with pytest.raises(PolicyPackError,match=part): PolicyPackLoader().load_yaml(f'name: x\nversion: 1.0.0\n{fragment}\npolicies: []\n')
def test_registry_resolved_packs():
    core=pack('core'); web=pack('web',deps=(PackDependency('core'),)); assert [p.name for p in PolicyPackRegistry((web,core)).resolved_packs(('web',))]==['core','web']
def test_registry_lock(): assert PolicyPackRegistry((pack('a'),)).lock().packs[0].name=='a'
def test_pack_dict_has_dependencies(): assert pack_to_dict(pack('a'))['dependencies']==[]
@pytest.mark.parametrize('n',range(10))
def test_repeated_resolution_is_stable(n):
    r=PolicyPackResolver((pack('b'),pack('a'))); assert r.resolve()==r.resolve() and r.lock()==r.lock()
