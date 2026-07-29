from __future__ import annotations

import random
import string

from moughorai.java_semantics import JavaSemanticFrontEnd


def test_java_method_parser_handles_deterministic_adversarial_inputs() -> None:
    generator = random.Random(106)
    alphabet = string.ascii_letters + string.digits + "{}()[];,.+-*/=!&|<>\"' \n\t"

    for _ in range(250):
        source = "".join(generator.choice(alphabet) for _ in range(generator.randrange(0, 160)))
        result = JavaSemanticFrontEnd().analyze_method_body(source)
        assert result.source == source
