import json
import pytest
from moughorai.dataflow import *
from moughorai.security_analysis import *

L=lambda p,n: SourceLocation(p,n,1)

def mid(name,arity=0,owner='App'): return MethodId(owner,name,arity)

def simple_program():
    controller=mid('controller',0); service=mid('service',1); repo=mid('repo',1)
    return DataFlowProgram((
        MethodFlow(controller,(),(),('response',),('request',),(),(('request',L('Controller.java',3)),('response',L('Controller.java',5)))),
        MethodFlow(service,('input',),(('clean','input'),),('clean',),(),(),(('input',L('Service.java',4)),('clean',L('Service.java',5)))),
        MethodFlow(repo,('query',),(),(),(),('query',),(('query',L('Repo.java',8)),)),
    ),(
        CallSite(controller,service,('request',),'response',L('Controller.java',5)),
        CallSite(service,repo,('clean',),None,L('Service.java',7)),
    ))

def finding(trace=()):
    return SecurityFinding('ATLAS-SQL-001','SQL injection','unsafe',Severity.CRITICAL,Confidence.HIGH,'CWE-89','A03:2021',L('Repo.java',8),trace)

def report(f): return SecurityReport((f,),ScanStatistics(1,1,1,0,0,0,0))

def test_method_id_qualified_name(): assert mid('x',2).qualified_name=='App.x/2'
def test_method_id_owner_optional(): assert MethodId('', 'x',0).qualified_name=='x/0'
def test_method_id_rejects_empty():
    with pytest.raises(ValueError): MethodId('','',0)
def test_method_id_rejects_negative_arity():
    with pytest.raises(ValueError): MethodId('','x',-1)
def test_method_flow_parameter_count():
    with pytest.raises(ValueError): MethodFlow(mid('x',1),())
def test_call_argument_count():
    with pytest.raises(ValueError): CallSite(mid('a'),mid('b',1),())
def test_duplicate_methods_rejected():
    m=MethodFlow(mid('a'))
    with pytest.raises(ValueError): DataFlowProgram((m,m))
def test_flow_node_rejects_empty_symbol():
    with pytest.raises(ValueError): FlowNode(mid('a'),' ',FlowRole.SOURCE)
def test_call_graph_edges():
    g=build_call_graph(simple_program()); assert len(g.edges)==2
def test_call_graph_deterministic():
    p=simple_program(); assert build_call_graph(p).to_dict()==build_call_graph(p).to_dict()
def test_call_graph_callers_and_callees():
    p=simple_program(); g=build_call_graph(p); assert g.callees(mid('controller'))==(mid('service',1),); assert g.callers(mid('repo',1))==(mid('service',1),)
def test_engine_rejects_bad_depth():
    with pytest.raises(ValueError): InterproceduralDataFlowEngine(0)
def test_simple_cross_method_flow_found():
    paths=InterproceduralDataFlowEngine().analyze(simple_program()); assert len(paths)==1 and paths[0].sink.symbol=='query'
def test_path_begins_source_and_ends_sink():
    p=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert p.nodes[0].role is FlowRole.SOURCE and p.nodes[-1].role is FlowRole.SINK
def test_parameter_propagation_present():
    p=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert any(n.role is FlowRole.PARAMETER for n in p.nodes)
def test_return_propagation_present():
    caller=mid('caller'); callee=mid('callee',1)
    program=DataFlowProgram((MethodFlow(caller,(),(),(),('request',),('result',)),MethodFlow(callee,('input',),(),('input',),(),())),(CallSite(caller,callee,('request',),'result',L('Caller.java',4)),))
    p=InterproceduralDataFlowEngine().analyze(program)[0]; assert any(n.role is FlowRole.RETURN for n in p.nodes)
def test_assignment_propagation_present():
    p=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert any(n.message=='input flows to clean' for n in p.nodes)
def test_locations_preserved():
    p=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert p.nodes[-1].location.path=='Repo.java'
def test_path_serialization():
    d=InterproceduralDataFlowEngine().analyze(simple_program())[0].to_dict(); assert d['nodes'][0]['role']=='source' and d['nodes'][-1]['role']=='sink'
def test_deterministic_analysis():
    e=InterproceduralDataFlowEngine(); assert e.analyze(simple_program())==e.analyze(simple_program())
def test_cache_used():
    e=InterproceduralDataFlowEngine(); e.analyze(simple_program()); assert e.cache_size==1
def test_cache_clear():
    e=InterproceduralDataFlowEngine(); e.analyze(simple_program()); e.clear_cache(); assert e.cache_size==0
def test_unknown_callee_ignored():
    a=mid('a'); p=DataFlowProgram((MethodFlow(a,(),(),(),('x',),('x',)),),(CallSite(a,mid('missing',1),('x',)),)); assert InterproceduralDataFlowEngine().analyze(p)[0].sink.symbol=='x'
def test_no_source_no_paths():
    assert InterproceduralDataFlowEngine().analyze(DataFlowProgram((MethodFlow(mid('a')),)))==()
def test_source_without_sink_no_complete_path():
    assert InterproceduralDataFlowEngine().analyze(DataFlowProgram((MethodFlow(mid('a'),sources=('x',)),)))==()
def test_depth_truncation():
    m=mid('a'); p=DataFlowProgram((MethodFlow(m,(),(('b','a'),('c','b'),('d','c')),(),('a',),('d',)),)); paths=InterproceduralDataFlowEngine(2).analyze(p); assert paths and paths[0].truncated
def test_recursion_detection():
    a=mid('a',1); p=DataFlowProgram((MethodFlow(a,('x',),(),('x',),('x',),()),),(CallSite(a,a,('x',),'x',L('A.java',2)),)); paths=InterproceduralDataFlowEngine().analyze(p); assert any(x.recursion_detected for x in paths)
def test_multiple_sources_sorted():
    m=mid('a'); p=DataFlowProgram((MethodFlow(m,(),(),(),('z','a'),('z','a')),)); paths=InterproceduralDataFlowEngine().analyze(p); assert [x.source.symbol for x in paths]==['a','z']
def test_multiple_sinks():
    m=mid('a'); p=DataFlowProgram((MethodFlow(m,(),(('b','a'),('c','a')),(),('a',),('b','c')),)); assert len(InterproceduralDataFlowEngine().analyze(p))==2
def test_path_source_sink_properties():
    p=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert p.source.symbol=='request' and p.sink.symbol=='query'
def test_empty_path_properties():
    p=FlowPath(()); assert p.source is None and p.sink is None
def test_finding_with_flow_trace():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; f=finding_with_flow(finding(),path); assert len(f.trace)==len(path.nodes)
def test_finding_with_flow_properties():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; f=finding_with_flow(finding(),path); assert dict(f.properties)['dataflow_version']=='1.0'
def test_finding_fingerprint_unchanged():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; assert finding_with_flow(finding(),path).fingerprint==finding().fingerprint
def test_sarif_code_flow_shape():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; d=sarif_code_flow(path); assert d['threadFlows'][0]['locations']
def test_sarif_code_flow_skips_missing_locations():
    d=sarif_code_flow(FlowPath((FlowNode(mid('a'),'x',FlowRole.SOURCE),))); assert d['threadFlows'][0]['locations']==[]
def test_exporter_emits_codeflows_for_trace():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; f=finding_with_flow(finding(),path); d=json.loads(SecurityReportExporter().to_sarif(report(f))); assert 'codeFlows' in d['runs'][0]['results'][0]
def test_exporter_omits_codeflows_without_trace():
    d=json.loads(SecurityReportExporter().to_sarif(report(finding()))); assert 'codeFlows' not in d['runs'][0]['results'][0]
def test_json_export_contains_dataflow_properties():
    path=InterproceduralDataFlowEngine().analyze(simple_program())[0]; f=finding_with_flow(finding(),path); d=SecurityReportExporter().to_dict(report(f)); assert d['findings'][0]['properties']['dataflow_version']=='1.0'
def test_engine_version(): assert InterproceduralDataFlowEngine.VERSION=='1.0'

@pytest.mark.parametrize('role',list(FlowRole))
def test_roles_are_strings(role): assert isinstance(role.value,str)

@pytest.mark.parametrize('depth',[1,2,4,8,16,32])
def test_depth_configuration(depth): assert InterproceduralDataFlowEngine(depth).max_depth==depth

@pytest.mark.parametrize('symbol',['a','value','request.body','x_1'])
def test_valid_symbols(symbol): assert FlowNode(mid('m'),symbol,FlowRole.SOURCE).symbol==symbol

@pytest.mark.parametrize('count',[1,2,3,5])
def test_linear_assignment_paths(count):
    m=mid('linear'); assignments=[]
    for i in range(count): assignments.append((f'x{i+1}',f'x{i}'))
    p=DataFlowProgram((MethodFlow(m,(),tuple(assignments),(),('x0',),(f'x{count}',)),)); path=InterproceduralDataFlowEngine().analyze(p)[0]; assert path.sink.symbol==f'x{count}'
