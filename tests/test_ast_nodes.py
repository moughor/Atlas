from moughorai.java_ast.ast_nodes import CompilationUnit
def test_empty_unit():
    assert CompilationUnit().imports==()
