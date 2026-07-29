from __future__ import annotations
from collections import defaultdict, deque
from .models import CallSite, DataFlowProgram, FlowNode, FlowPath, FlowRole, MethodFlow, MethodId
from .graph import build_call_graph

class InterproceduralDataFlowEngine:
    VERSION='1.0'
    def __init__(self,max_depth=32):
        if max_depth < 1: raise ValueError('max_depth must be positive')
        self.max_depth=max_depth; self._cache={}
    def clear_cache(self): self._cache.clear()
    @property
    def cache_size(self): return len(self._cache)
    def call_graph(self,program): return build_call_graph(program)
    def analyze(self,program:DataFlowProgram)->tuple[FlowPath,...]:
        key=(program,self.max_depth)
        if key in self._cache: return self._cache[key]
        methods=program.method_map(); adj=defaultdict(list)
        def add(a,b,role,loc=None,msg=''):
            adj[(a.method,a.symbol)].append((b,role,loc,msg))
        for m in program.methods:
            for target,source in m.assignments:
                add(FlowNode(m.method,source,FlowRole.PROPAGATION,m.location_for(source)),FlowNode(m.method,target,FlowRole.PROPAGATION,m.location_for(target)),FlowRole.PROPAGATION,m.location_for(target),f'{source} flows to {target}')
        calls=sorted(program.calls,key=lambda c:c.key)
        for c in calls:
            callee=methods.get(c.callee)
            if callee is None: continue
            for arg,param in zip(c.arguments,callee.parameters):
                add(FlowNode(c.caller,arg,FlowRole.CALL,c.location),FlowNode(c.callee,param,FlowRole.PARAMETER,callee.location_for(param)),FlowRole.PARAMETER,c.location,f'argument {arg} enters {c.callee.qualified_name} as {param}')
            if c.result:
                for ret in callee.returns:
                    add(FlowNode(c.callee,ret,FlowRole.RETURN,callee.location_for(ret)),FlowNode(c.caller,c.result,FlowRole.RETURN,c.location),FlowRole.RETURN,c.location,f'{c.callee.qualified_name} returns into {c.result}')
        starts=[]; sinks=set()
        for m in program.methods:
            starts.extend(FlowNode(m.method,s,FlowRole.SOURCE,m.location_for(s),f'tainted source {s}') for s in m.sources)
            sinks.update((m.method,s) for s in m.sinks)
        paths=[]
        for start in sorted(starts,key=lambda n:n.key):
            q=deque([(start,(start,),frozenset({(start.method,start.symbol)}),False)])
            while q:
                current,nodes,seen,recur=q.popleft()
                state=(current.method,current.symbol)
                if state in sinks:
                    sink=FlowNode(current.method,current.symbol,FlowRole.SINK,current.location,f'tainted value reaches sink {current.symbol}')
                    final=nodes if nodes[-1].role is FlowRole.SINK else nodes+(sink,)
                    paths.append(FlowPath(final,False,recur)); continue
                if len(nodes)>=self.max_depth:
                    paths.append(FlowPath(nodes,True,recur)); continue
                for nxt,role,loc,msg in sorted(adj.get(state,()),key=lambda x:x[0].key):
                    ns=(nxt.method,nxt.symbol); repeated=ns in seen
                    node=FlowNode(nxt.method,nxt.symbol,role,nxt.location or loc,msg)
                    if repeated:
                        paths.append(FlowPath(nodes+(node,),False,True)); continue
                    q.append((node,nodes+(node,),seen|{ns},recur))
        unique={tuple(n.key for n in p.nodes)+(p.truncated,p.recursion_detected):p for p in paths}
        result=tuple(unique[k] for k in sorted(unique,key=str))
        self._cache[key]=result; return result
