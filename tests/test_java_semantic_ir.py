from moughorai.java_semantic_ir import JavaMethodBodyParser


def test_extracts_local_variables_and_initializers():
    body = JavaMethodBodyParser().parse(
        "{ User user = repository.findById(id); int count = 1; }"
    )
    assert [(v.type_name, v.name) for v in body.local_variables] == [
        ("User", "user"),
        ("int", "count"),
    ]
    assert body.local_variables[0].initializer == "repository.findById(id)"


def test_extracts_method_calls():
    body = JavaMethodBodyParser().parse(
        "{ audit.log(user); repository.save(user); notify(); }"
    )
    assert [(c.qualifier, c.method_name) for c in body.calls] == [
        ("audit", "log"),
        ("repository", "save"),
        (None, "notify"),
    ]


def test_extracts_object_creation():
    body = JavaMethodBodyParser().parse("{ User user = new User(id, name); }")
    creation = body.object_creations[0]
    assert creation.type_name == "User"
    assert creation.arguments == ("id", "name")


def test_extracts_assignments_without_duplicate_local_declaration():
    body = JavaMethodBodyParser().parse(
        "{ int count = 1; count = count + 1; user.name = name; }"
    )
    assert [(a.target, a.expression) for a in body.assignments] == [
        ("count", "count + 1"),
        ("user.name", "name"),
    ]


def test_extracts_returns_and_control_statements():
    body = JavaMethodBodyParser().parse(
        "{ if (user == null) return null; return user; }"
    )
    assert [(c.kind, c.condition) for c in body.control_statements] == [
        ("if", "user == null"),
    ]
    assert [r.expression for r in body.returns] == ["user"]


def test_ignores_comments_and_string_contents():
    source = (
        "{\n"
        "  // repository.delete(user);\n"
        '  String text = "service.call()";\n'
        "  /* audit.log(user); */\n"
        "  repository.save(user);\n"
        "}"
    )
    body = JavaMethodBodyParser().parse(source)
    assert [(c.qualifier, c.method_name) for c in body.calls] == [
        ("repository", "save"),
    ]
