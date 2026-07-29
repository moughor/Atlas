# PR49 — Security Knowledge Base

PR49 adds a deterministic, versioned security knowledge catalog to Atlas. It maps analyzer rule identifiers to CWE, OWASP Top 10, MITRE technique identifiers, CVSS 3.1 metadata, remediation steps, safe and unsafe examples, and authoritative references.

The knowledge base is optional at export time. Existing findings and report schemas remain valid; callers that provide `SecurityKnowledgeBase()` receive an additional `knowledge` object in JSON and richer SARIF rule properties.

## API

```python
from moughorai.security_knowledge import SecurityKnowledgeBase
from moughorai.security_analysis.exporters import SecurityReportExporter

kb = SecurityKnowledgeBase()
entry = kb.require("ATLAS-SQL-001")
results = kb.search(cwe="CWE-89")
exporter = SecurityReportExporter(knowledge_base=kb)
```
