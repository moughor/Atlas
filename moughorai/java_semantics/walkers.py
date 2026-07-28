from __future__ import annotations
from dataclasses import fields, is_dataclass

class DepthFirstWalker:
    def enter(self, node) -> None:
        pass

    def leave(self, node) -> None:
        pass

    def walk(self, node) -> None:
        if node is None:
            return
        self.enter(node)
        if is_dataclass(node):
            for field in fields(node):
                value = getattr(node, field.name)
                if is_dataclass(value):
                    self.walk(value)
                elif isinstance(value, tuple):
                    for item in value:
                        if is_dataclass(item):
                            self.walk(item)
        self.leave(node)
