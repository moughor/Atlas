from dataclasses import dataclass
from moughorai.java_semantics.integration import Phase21SemanticAdapter
from moughorai.java_semantics.expressions import MethodCallExpression

@dataclass
class OldLocal:
    type_name: str
    name: str
    initializer: str | None

def test_phase21_adapter_parses_initializer():
    adapted = Phase21SemanticAdapter().adapt_local_variable(
        OldLocal("User", "user", "repo.find(id)")
    )
    assert adapted.type_name == "User"
    assert isinstance(adapted.initializer, MethodCallExpression)

def test_phase21_adapter_accepts_empty_initializer():
    adapted = Phase21SemanticAdapter().adapt_local_variable(
        OldLocal("User", "user", None)
    )
    assert adapted.initializer is None
