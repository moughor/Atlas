from __future__ import annotations
from moughorai.java_spring import SpringAnalysisReport
from .graph import RestEndpointGraph, endpoint_key, normalize_path
from .models import EndpointCall, HttpMethod, RestEndpoint

_ANNOTATION_METHOD={'GetMapping':HttpMethod.GET,'PostMapping':HttpMethod.POST,'PutMapping':HttpMethod.PUT,'PatchMapping':HttpMethod.PATCH,'DeleteMapping':HttpMethod.DELETE,'RequestMapping':HttpMethod.ANY}
class RestEndpointGraphBuilder:
    def build(self, report: SpringAnalysisReport, class_paths=None, calls=()):
        class_paths=class_paths or {}
        endpoints=[]
        for raw in report.endpoints:
            methods=tuple(raw.http_methods) or tuple(a for a in raw.annotations if a in _ANNOTATION_METHOD)
            methods=methods or ('ANY',)
            paths=raw.paths or ('/',)
            prefix=class_paths.get(raw.owner,'')
            for method in methods:
                hm=method if isinstance(method,HttpMethod) else _ANNOTATION_METHOD.get(str(method).split('.')[-1], HttpMethod.__members__.get(str(method).upper(),HttpMethod.ANY))
                for path in paths:
                    endpoints.append(RestEndpoint(raw.owner,raw.method_name,hm,normalize_path(f'{prefix}/{path}'),source_symbol=f'{raw.owner}#{raw.method_name}'))
        edges=[]
        keys={(e.owner,e.method_name):endpoint_key(e) for e in endpoints}
        for owner,method,target in calls:
            key=keys.get((owner,method))
            if key: edges.append(EndpointCall(key,target))
        return RestEndpointGraph(endpoints,edges)
