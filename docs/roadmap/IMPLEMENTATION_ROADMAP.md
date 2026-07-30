Atlas Implementation Roadmap
Version 2.x (PR122 – PR151)
---
Executive Summary
Atlas has successfully completed its first generation of semantic analysis.
Validated capabilities:
Java semantic parsing
Semantic snapshots
AI Explain
Ollama integration
Workspace model
Incremental analysis
3401 automated tests
End-to-end AI explanation pipeline
The next phase is no longer about proving the pipeline works.
The next phase is to make Atlas understand software.
---
Milestone A – Multi-Language Foundation
PR122 – Python Semantic Analyzer
Priority: ★★★★★
Goal
Provide semantic snapshots for Python repositories equivalent to the Java implementation.
Deliverables
PythonSemanticAnalyzer
classes
functions
decorators
async
imports
globals
dataclasses
enums
typing
docstrings
Acceptance Criteria
✓ Python repositories generate semantic snapshots
✓ atlas ai explain understands Python projects
---
PR123 – Project-Scoped Java Type Identity
Priority: ★★★★★
Goal
Allow identical fully qualified Java type names to exist in separate workspace projects or Gradle modules without being reported as duplicates.
Problem Confirmed
The JUnit workspace contains two legal default-package classes:
`jupiter-tests/src/test/java/DefaultPackageTestCase.java`
`platform-tests/src/test/java/DefaultPackageTestCase.java`
Atlas currently indexes both as `DefaultPackageTestCase` in one workspace-wide type registry and raises `DuplicateTypeError`.
Deliverables
Scope Java type identity by workspace project or module
Use a registry key equivalent to `(project_id, qualified_name)`
Preserve duplicate detection within the same project
Support duplicate default-package names across independent modules
Support duplicate fully qualified names across independent modules
Add regression fixtures based on the JUnit multi-project repository
Improve duplicate-type diagnostics with both source paths and project identities
Acceptance Criteria
✓ `atlas analyze . --no-recover` succeeds for the JUnit workspace
✓ `jupiter-tests:DefaultPackageTestCase` and `platform-tests:DefaultPackageTestCase` coexist
✓ A duplicate Java type inside one project still raises `DuplicateTypeError`
✓ Existing semantic snapshots and incremental analysis remain stable
---
PR124 – Analyzer Registry
Replace
SemanticProjectAnalyzer
with
AnalyzerRegistry
Supporting
Java
Python
Kotlin
JavaScript
TypeScript
Rust
Go
Acceptance
Language support becomes plugin-based.
---
PR125 – Cross-Language Workspace
Support repositories containing
Java
Python
TypeScript
within one semantic graph.
---
PR126 – Dependency Intelligence
Semantic understanding of
pom.xml
Gradle
requirements.txt
Poetry
package.json
Cargo.toml
---
PR127 – Framework Detection v2
Automatically detect
Spring
Quarkus
Micronaut
Flask
FastAPI
Django
SQLAlchemy
Celery
NestJS
React
Angular
---
Milestone B – Repository Intelligence
PR128 Repository Summary
PR129 Architecture Detection
PR130 Knowledge Graph
PR131 Design Pattern Detection
PR132 Dead Code Detection
PR133 Hotspot Ranking
PR134 AI Repository Report
---
Milestone C – AI Engineering Assistant
PR135 Explain Class
PR136 Explain Dependency
PR137 Semantic Search
PR138 Impact Prediction
PR139 Refactoring Suggestions
PR140 AI Security Review
PR141 Interactive Chat
---
Milestone D – Engineering Intelligence
PR142 Complexity Heatmap
PR143 Technical Debt
PR144 Repository Evolution
PR145 Architectural Drift
PR146 AI Quality Gates
---
Milestone E – Enterprise
PR147 Workspace Cache v2
PR148 Parallel Analysis
PR149 Shared Knowledge
PR150 IDE Integration
PR151 Atlas Server
---
Success Criteria
Atlas becomes capable of understanding large software systems instead of only parsing them.