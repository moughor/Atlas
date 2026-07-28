from __future__ import annotations
from typing import Any
from .models import Constraint, SymbolicKind, SymbolicState, SymbolicValue

UNKNOWN=object()

def evaluate(v:SymbolicValue,state:SymbolicState)->Any:
    if v.kind is SymbolicKind.CONSTANT:return v.value
    if v.kind is SymbolicKind.VARIABLE:
        resolved=dict(state.values).get(str(v.value))
        return UNKNOWN if resolved is None or resolved==v else evaluate(resolved,state)
    if v.kind is SymbolicKind.UNKNOWN:return UNKNOWN
    if v.kind is SymbolicKind.UNARY:
        x=evaluate(v.operands[0],state)
        if x is UNKNOWN:return UNKNOWN
        if v.operator=='not':return not x
        if v.operator=='-':return -x
    if v.kind is SymbolicKind.BINARY:
        a=evaluate(v.operands[0],state); b=evaluate(v.operands[1],state)
        if a is UNKNOWN or b is UNKNOWN:return UNKNOWN
        ops={'+':lambda:a+b,'-':lambda:a-b,'*':lambda:a*b,'/':lambda:a/b if b!=0 else UNKNOWN,
             '==':lambda:a==b,'!=':lambda:a!=b,'<':lambda:a<b,'<=':lambda:a<=b,'>':lambda:a>b,'>=':lambda:a>=b,
             'and':lambda:bool(a and b),'or':lambda:bool(a or b)}
        try:return ops[v.operator]() if v.operator in ops else UNKNOWN
        except (TypeError,ValueError,ZeroDivisionError):return UNKNOWN
    return UNKNOWN

def constraint_truth(c:Constraint,state:SymbolicState)->bool|None:
    a=evaluate(c.left,state); b=evaluate(c.right,state)
    if a is UNKNOWN or b is UNKNOWN:return None
    try:
        if c.operator == '==': return a == b
        if c.operator == '!=': return a != b
        if c.operator == '<': return a < b
        if c.operator == '<=': return a <= b
        if c.operator == '>': return a > b
        if c.operator == '>=': return a >= b
        if c.operator == 'is': return a is b
        if c.operator == 'is not': return a is not b
    except TypeError:
        return False
    return None

def is_feasible(state:SymbolicState)->bool:
    equal:dict[str,Any]={}; not_equal:dict[str,set[Any]]={}; lower:dict[str,tuple[Any,bool]]={}; upper:dict[str,tuple[Any,bool]]={}
    for c in state.constraints:
        truth=constraint_truth(c,state)
        if truth is False:return False
        if truth is True:continue
        left,right=c.left,c.right
        if left.kind is SymbolicKind.CONSTANT and right.kind is SymbolicKind.VARIABLE:
            left,right=right,left
            op={'<':'>','<=':'>=','>':'<','>=':'<=','==':'==','!=':'!=','is':'is','is not':'is not'}[c.operator]
        else: op=c.operator
        if left.kind is not SymbolicKind.VARIABLE or right.kind is not SymbolicKind.CONSTANT:continue
        name=str(left.value); val=right.value
        if op in {'==','is'}:
            if name in equal and equal[name]!=val:return False
            if val in not_equal.get(name,set()):return False
            equal[name]=val
        elif op in {'!=','is not'}:
            if equal.get(name,UNKNOWN)==val:return False
            not_equal.setdefault(name,set()).add(val)
        elif op in {'>','>='}: lower[name]=(val,op=='>=')
        elif op in {'<','<='}: upper[name]=(val,op=='<=')
    for name,val in equal.items():
        if name in lower:
            x,inc=lower[name]
            if val<x or (val==x and not inc):return False
        if name in upper:
            x,inc=upper[name]
            if val>x or (val==x and not inc):return False
    for name,(lo,li) in lower.items():
        if name in upper:
            hi,ui=upper[name]
            if lo>hi or (lo==hi and (not li or not ui)):return False
    return True
