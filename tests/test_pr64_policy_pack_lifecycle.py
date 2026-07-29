from dataclasses import replace
import json
import pytest

from moughorai.policy_packs import (
    PackDependency, PolicyPack, PolicyPackError, PolicyPackLifecycleManager,
    PolicyPackLoader,
)
from moughorai.taint_policy import MatchMode, SymbolMatcher, TaintPolicy
from moughorai.security_analysis.models import Confidence, Severity


def policy(rule_id):
    m=SymbolMatcher('source',MatchMode.EXACT)
    return TaintPolicy(rule_id,rule_id,'msg',(m,),(m,),severity=Severity.HIGH,confidence=Confidence.HIGH)


def pack(name='core',version='1.0.0',rules=('R1',),deps=(),metadata=()):
    return PolicyPack(name,version,tuple(policy(r) for r in rules),metadata=metadata,dependencies=deps)


def test_initial_state_sorted_and_active():
    mgr=PolicyPackLifecycleManager((pack('z'),pack('a',rules=('R2',))))
    assert [p.name for p in mgr.installed]==['a','z']
    assert mgr.active_names==('a','z')


def test_duplicate_initial_pack_rejected():
    with pytest.raises(PolicyPackError,match='duplicate'):
        PolicyPackLifecycleManager((pack(),pack()))


def test_unknown_active_rejected():
    with pytest.raises(PolicyPackError,match='not installed'):
        PolicyPackLifecycleManager((pack(),),active=('missing',))


def test_install_and_activate():
    mgr=PolicyPackLifecycleManager(())
    report=mgr.install(pack())
    assert report.changed and mgr.active_names==('core',)
    assert report.events[0].action=='installed'


def test_install_inactive():
    mgr=PolicyPackLifecycleManager(())
    mgr.install(pack(),activate=False)
    assert mgr.active_names==()


def test_duplicate_install_rejected():
    mgr=PolicyPackLifecycleManager((pack(),))
    with pytest.raises(PolicyPackError,match='already installed'):
        mgr.install(pack(version='2.0.0'))


def test_replace_install():
    mgr=PolicyPackLifecycleManager((pack(),))
    report=mgr.install(pack(version='2.0.0'),replace=True)
    assert report.current_version=='2.0.0'


def test_activate_noop():
    mgr=PolicyPackLifecycleManager((pack(),))
    assert not mgr.activate('core').changed


def test_activate_dependency_order():
    base=pack('base',rules=('B',))
    app=pack('app',rules=('A',),deps=(PackDependency('base','^1.0.0'),))
    mgr=PolicyPackLifecycleManager((base,app),active=('base',))
    mgr.activate('app')
    assert [p.name for p in mgr.registry().resolved_packs()]==['base','app']


def test_activate_missing_dependency_rejected():
    app=pack('app',deps=(PackDependency('base'),))
    mgr=PolicyPackLifecycleManager((app,),active=())
    with pytest.raises(PolicyPackError,match='missing'):
        mgr.activate('app')


def test_deactivate_referenced_pack_rejected():
    base=pack('base',rules=('B',)); app=pack('app',rules=('A',),deps=(PackDependency('base'),))
    mgr=PolicyPackLifecycleManager((base,app))
    with pytest.raises(PolicyPackError,match='dependents'):
        mgr.deactivate('base')


def test_deactivate_cascade():
    base=pack('base',rules=('B',)); app=pack('app',rules=('A',),deps=(PackDependency('base'),))
    mgr=PolicyPackLifecycleManager((base,app))
    mgr.deactivate('base',cascade=True)
    assert mgr.active_names==()


def test_uninstall_referenced_pack_rejected():
    base=pack('base',rules=('B',)); app=pack('app',rules=('A',),deps=(PackDependency('base'),))
    mgr=PolicyPackLifecycleManager((base,app))
    with pytest.raises(PolicyPackError,match='dependents'):
        mgr.uninstall('base')


def test_uninstall_cascade():
    base=pack('base',rules=('B',)); app=pack('app',rules=('A',),deps=(PackDependency('base'),))
    mgr=PolicyPackLifecycleManager((base,app))
    mgr.uninstall('base',cascade=True)
    assert mgr.installed==()


def test_rule_conflict_rejected():
    mgr=PolicyPackLifecycleManager((pack('one'),),active=('one',))
    with pytest.raises(PolicyPackError,match='rule conflict'):
        mgr.install(pack('two'))


def test_engine_compatibility_rejected():
    incompatible=pack(metadata=(('engine_api','>=2.0.0'),))
    with pytest.raises(PolicyPackError,match='requires engine'):
        PolicyPackLifecycleManager((incompatible,),engine_version='1.0.0')


def test_upgrade_success():
    mgr=PolicyPackLifecycleManager((pack(),))
    report=mgr.upgrade(pack(version='1.1.0'))
    assert report.changed and mgr.get('core').version=='1.1.0'


def test_upgrade_same_identical_is_noop():
    p=pack(); mgr=PolicyPackLifecycleManager((p,))
    assert not mgr.upgrade(p).changed


def test_same_version_different_content_rejected():
    mgr=PolicyPackLifecycleManager((pack(),))
    with pytest.raises(PolicyPackError,match='same-version'):
        mgr.upgrade(pack(rules=('R2',)))


def test_downgrade_rejected_by_default():
    mgr=PolicyPackLifecycleManager((pack(version='2.0.0'),))
    with pytest.raises(PolicyPackError,match='downgrade'):
        mgr.upgrade(pack(version='1.0.0'))


def test_downgrade_allowed():
    mgr=PolicyPackLifecycleManager((pack(version='2.0.0'),))
    assert mgr.upgrade(pack(version='1.0.0'),allow_downgrade=True).changed


def test_upgrade_rolls_back_when_dependency_breaks():
    base=pack('base','1.0.0',('B',)); app=pack('app',rules=('A',),deps=(PackDependency('base','^1.0.0'),))
    mgr=PolicyPackLifecycleManager((base,app))
    report=mgr.upgrade(pack('base','2.0.0',('B',)))
    assert report.rolled_back and mgr.get('base').version=='1.0.0'


def test_custom_validator_rolls_back():
    def validator(packs):
        if any(p.version=='2.0.0' for p in packs): raise RuntimeError('bad')
    mgr=PolicyPackLifecycleManager((pack(),),validator=validator)
    report=mgr.upgrade(pack(version='2.0.0'))
    assert report.rolled_back


def test_registry_contains_only_active():
    mgr=PolicyPackLifecycleManager((pack('a'),pack('b',rules=('B',))),active=('a',))
    assert [p.name for p in mgr.registry().packs]==['a']


def test_event_sequences_are_stable():
    mgr=PolicyPackLifecycleManager(())
    mgr.install(pack('a')); mgr.install(pack('b',rules=('B',)))
    assert [e.sequence for e in mgr.events]==[1,2]


def test_report_json_is_deterministic():
    mgr=PolicyPackLifecycleManager(())
    report=mgr.install(pack())
    assert report.to_json()==report.to_json()
    assert json.loads(report.to_json())['pack']=='core'


def test_export_state_deterministic():
    mgr=PolicyPackLifecycleManager((pack('b',rules=('B',)),pack('a')))
    assert mgr.export_state()==mgr.export_state()
    data=json.loads(mgr.export_state())
    assert [p['name'] for p in data['packs']]==['a','b']


def test_import_export_round_trip():
    mgr=PolicyPackLifecycleManager((pack(),))
    restored=PolicyPackLifecycleManager.import_state(mgr.export_state(),loader=PolicyPackLoader())
    assert restored.export_state()==mgr.export_state()


def test_import_invalid_json():
    with pytest.raises(PolicyPackError,match='invalid lifecycle'):
        PolicyPackLifecycleManager.import_state('{',loader=PolicyPackLoader())


def test_import_invalid_format():
    with pytest.raises(PolicyPackError,match='unsupported'):
        PolicyPackLifecycleManager.import_state('{"format_version": 9}',loader=PolicyPackLoader())


def test_get_unknown_pack():
    mgr=PolicyPackLifecycleManager(())
    with pytest.raises(PolicyPackError,match='not installed'):
        mgr.get('x')


def test_optional_missing_dependency_allowed():
    p=pack(deps=(PackDependency('optional','*',True),))
    assert PolicyPackLifecycleManager((p,)).active_names==('core',)
