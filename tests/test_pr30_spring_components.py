from pathlib import Path
from moughorai.java_spring import SpringAnalysisReport,SpringBean,SpringBeanKind
from moughorai.spring_components import *

def report():
 return SpringAnalysisReport(beans=(
  SpringBean('app.PaymentService',SpringBeanKind.SERVICE,('Service','Primary'),Path('PaymentService.java')),
  SpringBean('app.SqlOrderRepository',SpringBeanKind.REPOSITORY,('Repository','Qualifier:sql')),
  SpringBean('app.ApiController',SpringBeanKind.REST_CONTROLLER,('RestController',)),))
def catalog():return SpringComponentAnalyzer().analyze(report())
def test_count():assert len(catalog().components)==3
def test_sorted_names():assert [c.bean_name for c in catalog().components]==['apiController','paymentService','sqlOrderRepository']
def test_default_name():assert default_bean_name('app.XMLService')=='xMLService'
def test_service_kind():assert catalog().by_name('paymentService')[0].kind is ComponentKind.SERVICE
def test_repository_kind():assert catalog().by_name('sqlOrderRepository')[0].kind is ComponentKind.REPOSITORY
def test_controller_kind():assert catalog().by_name('apiController')[0].kind is ComponentKind.REST_CONTROLLER
def test_primary():assert catalog().by_name('paymentService')[0].primary
def test_non_primary():assert not catalog().by_name('apiController')[0].primary
def test_qualifier():assert catalog().by_name('sqlOrderRepository')[0].qualifiers==('sql',)
def test_exposed_self():assert catalog().by_type('app.PaymentService')[0].qualified_name=='app.PaymentService'
def test_missing_name():assert catalog().by_name('missing')==()
def test_missing_type():assert catalog().by_type('missing')==()
def test_primary_for():assert catalog().primary_for('app.PaymentService').bean_name=='paymentService'
def test_source():assert catalog().by_name('paymentService')[0].source==Path('PaymentService.java')
def test_immutable():
 import dataclasses; assert dataclasses.is_dataclass(catalog().components[0])
