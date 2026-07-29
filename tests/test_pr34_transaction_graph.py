from moughorai.transaction_graph import *
def graph(): return TransactionGraph((TransactionBoundary('A'),TransactionBoundary('B',Propagation.REQUIRES_NEW),TransactionBoundary('C',Propagation.NOT_SUPPORTED),TransactionBoundary('R',read_only=True)),(TransactionCall('A','B'),TransactionCall('B','C'),TransactionCall('R','W')))
def test_boundaries(): assert len(graph().boundaries)==4
def test_boundary(): assert graph().boundary('B').propagation is Propagation.REQUIRES_NEW
def test_callees(): assert graph().callees('A')==('B',)
def test_transitive_callees(): assert graph().callees('A',True)==('B','C')
def test_callers(): assert graph().callers('C')==('B',)
def test_transitive_callers(): assert graph().callers('C',True)==('A','B')
def test_flow_symbols(): assert graph().flow('A').symbols==('A','B','C')
def test_flow_new(): assert graph().flow('A').new_transactions==('B',)
def test_flow_suspended(): assert graph().flow('A').suspended_at==('C',)
def test_read_only_write(): assert graph().read_only_writes(('W',))==('R',)
def test_no_read_only_violation(): assert graph().read_only_writes(('X',))==()
def test_cycle():
 g=TransactionGraph(calls=(TransactionCall('A','B'),TransactionCall('B','A')));assert g.cycles()==(('A','B'),)
def test_acyclic(): assert graph().cycles()==()
def test_deduplicate_calls():
 c=TransactionCall('A','B');assert len(TransactionGraph(calls=(c,c)).calls)==1
def test_empty(): assert TransactionGraph().flow('A').symbols==('A',)
