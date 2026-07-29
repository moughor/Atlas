from __future__ import annotations
from dataclasses import replace
from typing import Any
from moughorai.symbolic_execution.models import Constraint, SymbolicKind, SymbolicState, SymbolicValue
from .models import CollectionFacts, Interval, SolveResult, StringFacts

_INVERT={'<':'>','<=':'>=','>':'<','>=':'<=','==':'==','!=':'!=','is':'is','is not':'is not'}

def _constant(v: SymbolicValue):
    return v.value if v.kind is SymbolicKind.CONSTANT else None

def _affine(v: SymbolicValue) -> tuple[str, float, float] | None:
    if v.kind is SymbolicKind.VARIABLE: return str(v.value), 1.0, 0.0
    if v.kind is SymbolicKind.UNARY and v.operator == '-':
        inner=_affine(v.operands[0]); return None if inner is None else (inner[0],-inner[1],-inner[2])
    if v.kind is SymbolicKind.BINARY:
        a,b=v.operands
        if v.operator in {'+','-'}:
            left=_affine(a); rc=_constant(b)
            if left is not None and isinstance(rc,(int,float)) and not isinstance(rc,bool):
                return left[0],left[1],left[2]+(rc if v.operator=='+' else -rc)
            right=_affine(b); lc=_constant(a)
            if v.operator=='+' and right is not None and isinstance(lc,(int,float)) and not isinstance(lc,bool):
                return right[0],right[1],right[2]+lc
        if v.operator=='*':
            left=_affine(a); rc=_constant(b)
            if left is not None and isinstance(rc,(int,float)) and not isinstance(rc,bool): return left[0],left[1]*rc,left[2]*rc
            right=_affine(b); lc=_constant(a)
            if right is not None and isinstance(lc,(int,float)) and not isinstance(lc,bool): return right[0],right[1]*lc,right[2]*lc
    return None

def _normalise_numeric(c: Constraint):
    la=_affine(c.left); rv=_constant(c.right); op=c.operator
    if la is None or not isinstance(rv,(int,float)) or isinstance(rv,bool):
        ra=_affine(c.right); lv=_constant(c.left)
        if ra is None or not isinstance(lv,(int,float)) or isinstance(lv,bool): return None
        la,rv,op=ra,lv,_INVERT[op]
    name,coef,offset=la
    if coef==0: return None
    target=(rv-offset)/coef
    if coef<0: op=_INVERT[op]
    return name,op,target

def _interval_for(op: str, value: float) -> Interval | None:
    if op in {'==','is'}: return Interval(value,True,value,True)
    if op=='>': return Interval(value,False,None,True)
    if op=='>=': return Interval(value,True,None,True)
    if op=='<': return Interval(None,True,value,False)
    if op=='<=': return Interval(None,True,value,True)
    return None

def _call(v: SymbolicValue, names: set[str]) -> tuple[str, tuple[SymbolicValue,...]] | None:
    if v.kind is SymbolicKind.BINARY and v.operator in names:
        receiver=v.operands[0]
        if receiver.kind is SymbolicKind.VARIABLE: return str(receiver.value),v.operands[1:]
    if v.kind is SymbolicKind.UNARY and v.operator in names:
        receiver=v.operands[0]
        if receiver.kind is SymbolicKind.VARIABLE:return str(receiver.value),()
    return None

def solve(state: SymbolicState) -> SolveResult:
    intervals: dict[str,Interval]={}; neq: dict[str,set[Any]]={}; strings: dict[str,StringFacts]={}; collections: dict[str,CollectionFacts]={}; bools: dict[str,bool]={}; nulls: dict[str,bool]={}; reasons=[]
    def fail(reason:str): return SolveResult(False,tuple(sorted(intervals.items())),tuple(sorted(strings.items())),tuple(sorted(collections.items())),tuple(sorted(bools.items())),tuple(sorted(nulls.items())),tuple(reasons+[reason]))
    for c in state.constraints:
        numeric=_normalise_numeric(c)
        if numeric and c.operator not in {'!=','is not'}:
            name,op,val=numeric; new=_interval_for(op,val)
            if new:
                merged=intervals.get(name,Interval()).intersect(new)
                if merged is None:return fail(f'empty numeric interval for {name}')
                intervals[name]=merged
                if op in {'==','is'} and val in neq.get(name,set()):return fail(f'{name} equals excluded value')
                continue
        left,right,op=c.left,c.right,c.operator
        if left.kind is SymbolicKind.CONSTANT and right.kind is SymbolicKind.VARIABLE:
            left,right,op=right,left,_INVERT[op]
        if left.kind is SymbolicKind.VARIABLE and right.kind is SymbolicKind.CONSTANT:
            name=str(left.value); val=right.value
            if val is None and op in {'==','is','!=','is not'}:
                is_null=op in {'==','is'}
                if name in nulls and nulls[name]!=is_null:return fail(f'conflicting nullability for {name}')
                nulls[name]=is_null; continue
            if isinstance(val,bool) and op in {'==','is','!=','is not'}:
                expected=val if op in {'==','is'} else not val
                if name in bools and bools[name]!=expected:return fail(f'conflicting boolean value for {name}')
                bools[name]=expected; continue
            if op in {'!=','is not'}:
                neq.setdefault(name,set()).add(val)
                iv=intervals.get(name)
                if iv and iv.lower==iv.upper==val:return fail(f'{name} equals excluded value')
                continue
            if isinstance(val,str) and op in {'==','is'}:
                old=strings.get(name,StringFacts())
                if old.equals is not None and old.equals!=val:return fail(f'conflicting string equality for {name}')
                sf=replace(old,equals=val,min_length=len(val),max_length=len(val))
                if any(not val.startswith(x) for x in sf.prefixes) or any(not val.endswith(x) for x in sf.suffixes) or any(x not in val for x in sf.contains) or any(x in val for x in sf.excludes):return fail(f'string facts contradict equality for {name}')
                strings[name]=sf; continue
        for opname,field in [('startsWith','prefixes'),('endsWith','suffixes'),('contains','contains')]:
            called=_call(left,{opname})
            if called and right.kind is SymbolicKind.CONSTANT and isinstance(right.value,bool) and op in {'==','is'}:
                name,args=called
                if not args or args[0].kind is not SymbolicKind.CONSTANT or not isinstance(args[0].value,str):continue
                token=args[0].value; expected=right.value; old=strings.get(name,StringFacts())
                if opname=='contains' and not expected:
                    sf=replace(old,excludes=tuple(sorted(set(old.excludes+(token,)))))
                elif expected:
                    vals=tuple(sorted(set(getattr(old,field)+(token,)))); sf=replace(old,**{field:vals},min_length=max(old.min_length,len(token)))
                else: continue
                if sf.equals is not None:
                    actual = sf.equals.startswith(token) if opname=='startsWith' else sf.equals.endswith(token) if opname=='endsWith' else token in sf.equals
                    if actual != expected:return fail(f'string predicate contradicts equality for {name}')
                if token in sf.contains and token in sf.excludes:return fail(f'conflicting contains facts for {name}')
                strings[name]=sf
        length=_call(left,{'length','size'})
        if length and right.kind is SymbolicKind.CONSTANT and isinstance(right.value,int) and op in {'==','>=','>','<=','<'}:
            name,_=length; n=right.value; old=collections.get(name,CollectionFacts())
            lo,hi=old.min_size,old.max_size
            if op=='==':lo=hi=n
            elif op=='>=':lo=max(lo,n)
            elif op=='>':lo=max(lo,n+1)
            elif op=='<=':hi=n if hi is None else min(hi,n)
            elif op=='<':hi=n-1 if hi is None else min(hi,n-1)
            if hi is not None and lo>hi:return fail(f'empty collection size interval for {name}')
            if old.empty is False and hi == 0:return fail(f'conflicting emptiness for {name}')
            if old.empty is True and lo > 0:return fail(f'conflicting emptiness for {name}')
            collections[name]=CollectionFacts(lo,hi, hi==0 if hi==0 else (False if lo>0 else old.empty))
        empty=_call(left,{'isEmpty'})
        if empty and right.kind is SymbolicKind.CONSTANT and isinstance(right.value,bool) and op in {'==','is'}:
            name,_=empty; expected=right.value; old=collections.get(name,CollectionFacts())
            new=CollectionFacts(0,0,True) if expected else CollectionFacts(max(1,old.min_size),old.max_size,False)
            if new.max_size is not None and new.min_size>new.max_size:return fail(f'conflicting emptiness for {name}')
            collections[name]=new
    for name,iv in intervals.items():
        if iv.lower==iv.upper and iv.lower in neq.get(name,set()):return fail(f'{name} equals excluded value')
    return SolveResult(True,tuple(sorted(intervals.items())),tuple(sorted(strings.items())),tuple(sorted(collections.items())),tuple(sorted(bools.items())),tuple(sorted(nulls.items())),tuple(reasons))

def is_feasible_advanced(state: SymbolicState) -> bool:
    return solve(state).feasible
