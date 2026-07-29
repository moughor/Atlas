from pathlib import Path
import pytest
from moughorai.workspace import ConfigurationLayer,WorkspaceConfigurationError,WorkspaceConfigurationResolver,WorkspaceService

def test_empty_name():
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer(' ',{})
def test_non_mapping():
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer('x',[])
def test_single(): assert WorkspaceConfigurationResolver().resolve(ConfigurationLayer('g',{'x':1})).get('x')==1
def test_override_scalar():
    r=WorkspaceConfigurationResolver().resolve(ConfigurationLayer('a',{'x':1}),ConfigurationLayer('b',{'x':2})); assert (r.get('x'),r.source_of('x'))==(2,'b')
def test_nested_merge():
    r=WorkspaceConfigurationResolver().for_project(global_values={'a':{'x':1,'y':2}},workspace_values={'a':{'x':3}}); assert r.get('a.x')==3 and r.get('a.y')==2
def test_list_replace(): assert WorkspaceConfigurationResolver().for_project(global_values={'x':[1]},project_values={'x':[2]}).get('x')==[2]
def test_project_precedence(): assert WorkspaceConfigurationResolver().for_project(workspace_values={'x':1},project_values={'x':2}).get('x')==2
def test_cli_precedence(): assert WorkspaceConfigurationResolver().for_project(project_values={'a':{'b':1}},cli_overrides={'a.b':2}).get('a.b')==2
def test_cli_nested(): assert WorkspaceConfigurationResolver().for_project(cli_overrides={'a.b.c':1}).to_dict()=={'a':{'b':{'c':1}}}
def test_cli_bad_key():
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer.from_overrides({'a..b':1})
def test_cli_scalar_collision():
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer.from_overrides({'a':1,'a.b':2})
def test_default(): assert WorkspaceConfigurationResolver().for_project().get('x',7)==7
def test_require(): assert WorkspaceConfigurationResolver().for_project(global_values={'x':3}).require('x')==3
def test_require_missing():
    with pytest.raises(KeyError): WorkspaceConfigurationResolver().for_project().require('x')
def test_layers(): assert WorkspaceConfigurationResolver().for_project(cli_overrides={'x':1}).layers==('global','workspace','project','cli')
def test_copy_input():
    x={'a':{'b':1}}; l=ConfigurationLayer('x',x); x['a']['b']=9; assert l.values['a']['b']==1
def test_tuple_normalized(): assert ConfigurationLayer('x',{'a':(1,2)}).values['a']==[1,2]
def test_types_preserved():
    r=WorkspaceConfigurationResolver().for_project(global_values={'n':2,'b':True}); assert r.get('n')==2 and r.get('b') is True
def test_nested_provenance():
    r=WorkspaceConfigurationResolver().for_project(global_values={'a':{'x':1,'y':2}},workspace_values={'a':{'x':3}}); assert r.source_of('a.x')=='workspace' and r.source_of('a.y')=='global'
def test_unknown_source(): assert WorkspaceConfigurationResolver().for_project().source_of('x') is None
def test_file_yaml(tmp_path:Path):
    p=tmp_path/'x.yaml'; p.write_text('a:\n  b: true\n'); assert ConfigurationLayer.from_file('x',p).values['a']['b'] is True
def test_empty_file(tmp_path:Path):
    p=tmp_path/'x.yaml'; p.write_text(''); assert ConfigurationLayer.from_file('x',p).values=={}
def test_file_bad_root(tmp_path:Path):
    p=tmp_path/'x.yaml'; p.write_text('- x\n');
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer.from_file('x',p)
def test_optional_missing(tmp_path:Path): assert ConfigurationLayer.from_file('x',tmp_path/'none',optional=True).values=={}
def test_required_missing(tmp_path:Path):
    with pytest.raises(FileNotFoundError): ConfigurationLayer.from_file('x',tmp_path/'none')
def test_bad_yaml(tmp_path:Path):
    p=tmp_path/'x.yaml'; p.write_text('a: [\n');
    with pytest.raises(WorkspaceConfigurationError): ConfigurationLayer.from_file('x',p)
def test_service_project(tmp_path:Path):
    (tmp_path/'api').mkdir(); (tmp_path/'atlas.yaml').write_text('options:\n  mode: workspace\nprojects:\n- name: api\n  path: api\n  options:\n    mode: project\n'); assert WorkspaceService(tmp_path).resolved_configuration('api').get('mode')=='project'
def test_service_global(tmp_path:Path):
    (tmp_path/'api').mkdir(); (tmp_path/'atlas.yaml').write_text('options:\n  mode: workspace\nprojects:\n- name: api\n  path: api\n'); assert WorkspaceService(tmp_path).resolved_configuration('api',global_values={'mode':'global'}).get('mode')=='workspace'
def test_service_cli(tmp_path:Path):
    (tmp_path/'api').mkdir(); (tmp_path/'atlas.yaml').write_text('projects:\n- name: api\n  path: api\n  options:\n    mode: project\n'); assert WorkspaceService(tmp_path).resolved_configuration('api',cli_overrides={'mode':'cli'}).get('mode')=='cli'
def test_to_dict_copy():
    r=WorkspaceConfigurationResolver().for_project(global_values={'a':{'b':1}}); d=r.to_dict(); d['a']['b']=9; assert r.get('a.b')==1
