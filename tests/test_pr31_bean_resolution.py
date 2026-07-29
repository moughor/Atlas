from moughorai.spring_components import *
from moughorai.bean_resolution import *
def bean(q,name,*,types=('app.Store',),qual=(),primary=False):return ComponentDefinition(q,ComponentKind.SERVICE,name,types,qual,primary)
def resolver():return BeanResolver(ComponentCatalog((bean('app.SqlStore','sqlStore',qual=('sql',)),bean('app.MemoryStore','memoryStore',qual=('memory',)),bean('app.PrimaryStore','primaryStore',primary=True))))
def test_primary_resolution():assert resolver().resolve(BeanResolutionRequest('app.Store')).bean.bean_name=='primaryStore'
def test_primary_status():assert resolver().resolve(BeanResolutionRequest('app.Store')).status is BeanResolutionStatus.RESOLVED
def test_qualifier():assert resolver().resolve(BeanResolutionRequest('app.Store',qualifier='sql')).bean.bean_name=='sqlStore'
def test_bean_name_qualifier():assert resolver().resolve(BeanResolutionRequest('app.Store',qualifier='memoryStore')).bean.bean_name=='memoryStore'
def test_missing():assert resolver().resolve(BeanResolutionRequest('app.Unknown')).status is BeanResolutionStatus.MISSING
def test_missing_reason():assert resolver().resolve(BeanResolutionRequest('app.Unknown')).reason=='no candidate'
def test_optional_reason():assert resolver().resolve(BeanResolutionRequest('app.Unknown',required=False)).reason=='optional missing'
def test_ambiguous():
 r=BeanResolver(ComponentCatalog((bean('a.A','a'),bean('a.B','b'))));assert r.resolve(BeanResolutionRequest('app.Store')).status is BeanResolutionStatus.AMBIGUOUS
def test_candidates_sorted():
 r=BeanResolver(ComponentCatalog((bean('a.B','b'),bean('a.A','a')))).resolve(BeanResolutionRequest('app.Store'));assert [c.bean_name for c in r.candidates]==['a','b']
def test_injection_name_breaks_tie():
 r=BeanResolver(ComponentCatalog((bean('a.A','a'),bean('a.B','b'))));assert r.resolve(BeanResolutionRequest('app.Store',injection_name='b')).bean.bean_name=='b'
def test_exact_qualified_type():
 c=bean('app.Special','special',types=());assert BeanResolver(ComponentCatalog((c,))).resolve(BeanResolutionRequest('app.Special')).bean==c
def test_bad_qualifier_missing():assert resolver().resolve(BeanResolutionRequest('app.Store',qualifier='bad')).status is BeanResolutionStatus.MISSING
def test_unique_candidate_reason():assert resolver().resolve(BeanResolutionRequest('app.Store',qualifier='sql')).reason=='unique candidate'
def test_result_request_preserved():
 q=BeanResolutionRequest('app.Store',qualifier='sql');assert resolver().resolve(q).request==q
def test_request_defaults():assert BeanResolutionRequest('x').required
