from __future__ import annotations
from collections import defaultdict
from .models import EndpointCall, EndpointConflict, HttpMethod, RestEndpoint

def normalize_path(path: str) -> str:
    value='/' + '/'.join(part for part in str(path or '').strip().split('/') if part)
    return value if value != '' else '/'

def endpoint_key(endpoint: RestEndpoint) -> str:
    return f'{endpoint.http_method.value} {endpoint.path} -> {endpoint.owner}#{endpoint.method_name}'

class RestEndpointGraph:
    def __init__(self, endpoints=(), calls=()):
        normalized=[]
        for e in endpoints:
            normalized.append(RestEndpoint(e.owner,e.method_name,e.http_method,normalize_path(e.path),tuple(e.consumes),tuple(e.produces),e.source_symbol))
        self._endpoints=tuple(sorted(set(normalized)))
        self._calls=tuple(sorted(set(calls)))
        self._by_route=defaultdict(list)
        self._by_owner=defaultdict(list)
        self._targets=defaultdict(set)
        for e in self._endpoints:
            self._by_route[(e.http_method,e.path)].append(e)
            self._by_owner[e.owner].append(e)
        for call in self._calls: self._targets[call.endpoint_key].add(call.target_symbol)
    @property
    def endpoints(self): return self._endpoints
    @property
    def calls(self): return self._calls
    def routes(self, method: HttpMethod, path: str): return tuple(self._by_route.get((method,normalize_path(path)),()))
    def endpoints_for(self, owner: str): return tuple(self._by_owner.get(owner,()))
    def targets(self, endpoint: RestEndpoint | str):
        key=endpoint_key(endpoint) if isinstance(endpoint,RestEndpoint) else endpoint
        return tuple(sorted(self._targets.get(key,())))
    def conflicts(self):
        out=[]
        for (method,path), endpoints in self._by_route.items():
            if len(endpoints)>1: out.append(EndpointConflict(method,path,tuple(sorted(endpoint_key(e) for e in endpoints))))
        return tuple(sorted(out,key=lambda c:(c.http_method.value,c.path)))
