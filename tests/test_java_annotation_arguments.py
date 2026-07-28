from moughorai.java_ast.parser import JavaParser


def test_parser_preserves_named_and_default_annotation_arguments() -> None:
    unit = JavaParser().parse_source('''
        @Entity(name = "UserEntity")
        @Table(name="users", schema="app")
        class User {
            @Column(name="user_id", nullable=false)
            String id;

            @GetMapping({"/one", "/two"})
            String get() { return id; }
        }
    ''')
    declaration = unit.types[0]
    assert declaration.annotations == ("Entity", "Table")
    table = declaration.annotation_nodes[1]
    assert table.argument("name") == '"users"'
    assert table.argument("schema") == '"app"'
    column = declaration.fields[0].annotation_nodes[0]
    assert column.argument("nullable") == "false"
    mapping = declaration.methods[0].annotation_nodes[0]
    assert mapping.argument() == '{"/one","/two"}'
