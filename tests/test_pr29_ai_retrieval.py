from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.semantic_search import *
from moughorai.knowledge_graph import *
from moughorai.context_builder import *
from moughorai.ai_retrieval import *

def service():
 a=GlobalSymbol.create(GlobalSymbolKind.TYPE,'PaymentService','app.PaymentService'); db=GlobalSymbolDatabase([a]); dg=DependencyGraph(); return AIRetrievalService(ContextBuilder(db,SemanticSearchService(db,dg),KnowledgeGraphBuilder().build(db,dg)))
def test_retrieve_question(): r=service().retrieve(RetrievalRequest('PaymentService')); assert r.question=='PaymentService'
def test_citation(): r=service().retrieve(RetrievalRequest('PaymentService')); assert r.citations==('app.PaymentService',)
def test_context_present(): assert service().retrieve(RetrievalRequest('PaymentService')).context.items
def test_confidence_positive(): assert service().retrieve(RetrievalRequest('PaymentService')).confidence>0
def test_missing_zero_confidence(): assert service().retrieve(RetrievalRequest('missing')).confidence==0.0
def test_missing_no_citations(): assert service().retrieve(RetrievalRequest('missing')).citations==()
def test_max_symbols_forwarded(): assert len(service().retrieve(RetrievalRequest('',max_symbols=0)).context.items)==0
def test_max_chars_forwarded(): assert service().retrieve(RetrievalRequest('PaymentService',max_chars=1)).context.truncated
def test_deterministic(): s=service(); assert s.retrieve(RetrievalRequest('PaymentService'))==s.retrieve(RetrievalRequest('PaymentService'))
def test_confidence_bounded(): assert 0<=service().retrieve(RetrievalRequest('PaymentService')).confidence<=1
def test_context_query_matches(): assert service().retrieve(RetrievalRequest('PaymentService')).context.query=='PaymentService'
def test_citations_unique(): r=service().retrieve(RetrievalRequest('PaymentService')); assert len(r.citations)==len(set(r.citations))
def test_context_text(): assert 'app.PaymentService' in service().retrieve(RetrievalRequest('PaymentService')).context.text
def test_result_immutable():
 import dataclasses; assert dataclasses.is_dataclass(service().retrieve(RetrievalRequest('PaymentService')))
def test_request_defaults(): assert RetrievalRequest('x').max_symbols==20
