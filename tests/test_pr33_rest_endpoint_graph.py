from moughorai.java_spring import SpringAnalysisReport,SpringEndpoint
from moughorai.rest_endpoint_graph import *

def report(): return SpringAnalysisReport(endpoints=(SpringEndpoint('app.UserController','get',('GET',),(),('/users/{id}',)),SpringEndpoint('app.UserController','create',('POST',),(),('/users',))))
def graph(): return RestEndpointGraphBuilder().build(report(),{'app.UserController':'/api'},(('app.UserController','get','app.UserService#find'),))
def test_count(): assert len(graph().endpoints)==2
def test_prefix(): assert graph().endpoints[0].path.startswith('/api/')
def test_normalize(): assert normalize_path('//api///users/')=='/api/users'
def test_route_lookup(): assert graph().routes(HttpMethod.GET,'/api/users/{id}')[0].method_name=='get'
def test_owner_lookup(): assert len(graph().endpoints_for('app.UserController'))==2
def test_target(): assert graph().targets(graph().routes(HttpMethod.GET,'/api/users/{id}')[0])==('app.UserService#find',)
def test_no_conflict(): assert graph().conflicts()==()
def test_conflict():
 e1=RestEndpoint('A','a',HttpMethod.GET,'/x');e2=RestEndpoint('B','b',HttpMethod.GET,'/x');assert len(RestEndpointGraph((e1,e2)).conflicts())==1
def test_key(): assert endpoint_key(RestEndpoint('A','m',HttpMethod.GET,'/x'))=='GET /x -> A#m'
def test_any_mapping():
 r=SpringAnalysisReport(endpoints=(SpringEndpoint('A','m',(),('RequestMapping',),('/x',)),));assert RestEndpointGraphBuilder().build(r).endpoints[0].http_method is HttpMethod.ANY
def test_annotation_mapping():
 r=SpringAnalysisReport(endpoints=(SpringEndpoint('A','m',(),('DeleteMapping',),('/x',)),));assert RestEndpointGraphBuilder().build(r).endpoints[0].http_method is HttpMethod.DELETE
def test_default_path():
 r=SpringAnalysisReport(endpoints=(SpringEndpoint('A','m',('GET',),()),));assert RestEndpointGraphBuilder().build(r).endpoints[0].path=='/'
def test_deduplicate():
 e=RestEndpoint('A','m',HttpMethod.GET,'/x');assert len(RestEndpointGraph((e,e)).endpoints)==1
def test_calls_sorted():
 c1=EndpointCall('b','z');c2=EndpointCall('a','x');assert RestEndpointGraph(calls=(c1,c2)).calls==(c2,c1)
def test_empty(): assert RestEndpointGraph().endpoints==()
