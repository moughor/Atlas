from __future__ import annotations

import re


class JavaConfigurationParser:
    def parse(self, path: str, content: str) -> tuple[tuple[str, str], ...]:
        lowered = path.lower()
        values = self._parse_properties(content) if lowered.endswith(".properties") else self._parse_yaml(content)
        values.setdefault("config_path", path)
        return tuple(sorted(values.items()))

    def _parse_properties(self, content: str) -> dict[str, str]:
        values: dict[str, str] = {}
        pending = ""
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "!")):
                continue
            if line.endswith("\\"):
                pending += line[:-1]
                continue
            line = pending + line
            pending = ""
            match = re.match(r"([^:=\s]+)\s*[:=]\s*(.*)$", line)
            if match:
                values[match.group(1).strip()] = match.group(2).strip()
        return values

    def _parse_yaml(self, content: str) -> dict[str, str]:
        values: dict[str, str] = {}
        stack: list[tuple[int, str]] = []
        for raw in content.splitlines():
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            match = re.match(r"\s*([^:#]+):(?:\s*(.*))?$", raw)
            if not match:
                continue
            key, value = match.group(1).strip(), (match.group(2) or "").strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if value:
                full = ".".join([part for _, part in stack] + [key])
                values[full] = value.strip('"\'')
            else:
                stack.append((indent, key))
        return values
