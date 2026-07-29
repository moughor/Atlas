import pytest
from moughorai.advanced_symbolic import Interval, solve
from moughorai.symbolic_execution import Constraint, SymbolicState, SymbolicValue, is_feasible

V=SymbolicValue.variable
C=SymbolicValue.constant
B=SymbolicValue.binary
U=SymbolicValue.unary

def state(*constraints): return SymbolicState(constraints=tuple(constraints))
def con(left,op,right): return Constraint(left,op,right)

def call1(name,receiver,arg): return B(name,V(receiver),C(arg))
def call0(name,receiver): return U(name,V(receiver))

@pytest.mark.parametrize('constraints,expected',[
    ((con(V('x'),'>',C(0)),con(V('x'),'<',C(10))),True),
    ((con(V('x'),'>',C(10)),con(V('x'),'<',C(0))),False),
    ((con(V('x'),'>=',C(5)),con(V('x'),'<=',C(5))),True),
    ((con(V('x'),'>',C(5)),con(V('x'),'<=',C(5))),False),
    ((con(B('+',V('x'),C(2)),'<',C(5)),con(V('x'),'>=',C(3))),False),
    ((con(B('-',V('x'),C(2)),'>=',C(5)),con(V('x'),'<',C(7))),False),
    ((con(B('*',V('x'),C(2)),'>',C(10)),con(V('x'),'<=',C(5))),False),
    ((con(B('*',V('x'),C(-2)),'>',C(10)),con(V('x'),'>=',C(-5))),False),
    ((con(U('-',V('x')),'>',C(3)),con(V('x'),'>=',C(-3))),False),
    ((con(C(4),'<',B('+',V('x'),C(1))),con(V('x'),'<=',C(3))),False),
    ((con(V('x'),'==',C(7)),con(V('x'),'!=',C(7))),False),
    ((con(V('x'),'==',C(7)),con(V('x'),'!=',C(8))),True),
    ((con(V('x'),'>=',C(-1)),con(V('x'),'<=',C(1))),True),
    ((con(B('+',C(2),V('x')),'==',C(5)),con(V('x'),'!=',C(3))),False),
    ((con(B('*',C(3),V('x')),'==',C(12)),con(V('x'),'!=',C(4))),False),
])
def test_numeric_feasibility(constraints,expected):
    assert is_feasible(state(*constraints)) is expected

@pytest.mark.parametrize('constraints,expected',[
    ((con(V('flag'),'==',C(True)),con(V('flag'),'==',C(False))),False),
    ((con(V('flag'),'!=',C(True)),con(V('flag'),'==',C(False))),True),
    ((con(V('x'),'is',C(None)),con(V('x'),'is not',C(None))),False),
    ((con(V('x'),'is not',C(None)),),True),
    ((con(V('a'),'==',C(True)),con(V('b'),'==',C(False))),True),
    ((con(V('a'),'is',C(False)),con(V('a'),'!=',C(False))),False),
])
def test_boolean_and_nullability(constraints,expected):
    assert is_feasible(state(*constraints)) is expected

@pytest.mark.parametrize('constraints,expected',[
    ((con(call1('startsWith','s','admin'),'==',C(True)),con(V('s'),'==',C('guest'))),False),
    ((con(call1('startsWith','s','adm'),'==',C(True)),con(V('s'),'==',C('admin'))),True),
    ((con(call1('endsWith','s','.xml'),'==',C(True)),con(V('s'),'==',C('a.json'))),False),
    ((con(call1('endsWith','s','.xml'),'==',C(True)),con(V('s'),'==',C('a.xml'))),True),
    ((con(call1('contains','s','../'),'==',C(True)),con(V('s'),'==',C('safe/path'))),False),
    ((con(call1('contains','s','../'),'==',C(False)),con(V('s'),'==',C('../etc'))),False),
    ((con(call1('contains','s','abc'),'==',C(True)),con(call1('contains','s','abc'),'==',C(False))),False),
    ((con(call1('startsWith','s','abcdef'),'==',C(True)),),True),
    ((con(V('s'),'==',C('hello')),con(V('s'),'==',C('world'))),False),
    ((con(V('s'),'==',C('hello')),con(call1('contains','s','ell'),'==',C(True))),True),
    ((con(V('s'),'==',C('hello')),con(call1('startsWith','s','he'),'==',C(True))),True),
    ((con(V('s'),'==',C('hello')),con(call1('endsWith','s','lo'),'==',C(True))),True),
])
def test_string_reasoning(constraints,expected):
    assert is_feasible(state(*constraints)) is expected

@pytest.mark.parametrize('constraints,expected',[
    ((con(call0('size','xs'),'>=',C(2)),con(call0('size','xs'),'<',C(2))),False),
    ((con(call0('length','xs'),'==',C(0)),con(call0('isEmpty','xs'),'==',C(False))),False),
    ((con(call0('isEmpty','xs'),'==',C(True)),con(call0('size','xs'),'>',C(0))),False),
    ((con(call0('isEmpty','xs'),'==',C(False)),con(call0('size','xs'),'==',C(0))),False),
    ((con(call0('size','xs'),'>=',C(1)),con(call0('size','xs'),'<=',C(3))),True),
    ((con(call0('length','text'),'==',C(5)),),True),
    ((con(call0('size','xs'),'<',C(0)),),False),
    ((con(call0('size','xs'),'>=',C(0)),),True),
    ((con(call0('size','xs'),'==',C(4)),con(call0('size','xs'),'!=',C(5))),True),
])
def test_collection_reasoning(constraints,expected):
    assert is_feasible(state(*constraints)) is expected

def test_interval_intersection():
    assert Interval(0,True,10,False).intersect(Interval(5,False,20,True)) == Interval(5,False,10,False)

def test_interval_empty_intersection():
    assert Interval(0,True,1,True).intersect(Interval(2,True,3,True)) is None

def test_interval_contains_boundaries():
    i=Interval(0,False,2,True); assert not i.contains(0) and i.contains(2)

def test_solve_exposes_interval():
    r=solve(state(con(V('x'),'>=',C(2)),con(V('x'),'<',C(8))))
    assert dict(r.intervals)['x']==Interval(2,True,8,False)

def test_solve_exposes_string_facts():
    r=solve(state(con(call1('startsWith','s','api/'),'==',C(True))))
    assert dict(r.strings)['s'].prefixes==('api/',)

def test_solve_exposes_collection_facts():
    r=solve(state(con(call0('isEmpty','items'),'==',C(False))))
    assert dict(r.collections)['items'].min_size==1

def test_solve_exposes_boolean_facts():
    assert dict(solve(state(con(V('ok'),'==',C(True)))).booleans)['ok'] is True

def test_solve_exposes_nullability_facts():
    assert dict(solve(state(con(V('x'),'is not',C(None)))).nullability)['x'] is False

def test_contradiction_reason_is_deterministic():
    r=solve(state(con(V('x'),'>',C(5)),con(V('x'),'<=',C(5))))
    assert r.reasons==('empty numeric interval for x',)
