# PR50 — AI Explanation Engine

PR50 adds deterministic, evidence-grounded explanations for Atlas security findings. The engine combines analyzer evidence with PR49 knowledge entries to produce a vulnerability summary, impact statement, confidence rationale, ordered source-to-sink path, remediation plan, examples, taxonomy, and references.

The local explanation is authoritative and requires no network service. A provider interface may polish the resulting immutable explanation, but providers cannot change finding identity or detector behavior.

```python
from moughorai.security_explanations import SecurityExplanationEngine
from moughorai.security_analysis.exporters import SecurityReportExporter

engine = SecurityExplanationEngine()
explanation = engine.explain(finding)
exporter = SecurityReportExporter(knowledge_base=engine.knowledge_base, explanation_engine=engine)
```
