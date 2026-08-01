from __future__ import annotations

from collections.abc import Mapping, Sequence
from html import escape as escape_html
from typing import Any

__all__ = ["RepositoryReportRenderer"]


class RepositoryReportRenderer:
    """Render a source-free repository context without generative inference.

    The renderer deliberately performs presentation only.  It does not derive
    repository conclusions, fill missing values, or ask an LLM to interpret
    the supplied semantic context.
    """

    _INVENTORY_LABELS = {
        "inventoried_file_count": "Inventoried files",
        "inventoried_files": "Inventoried files",
        "inventoried_file_bytes": "Inventoried file size",
        "inventoried_file_size_error_count": "Inventoried file size errors",
        "classified_non_test_source_files": "Classified non-test source files",
        "classified_test_source_files": "Classified test source files",
        "classified_generated_files": "Classified generated files",
        "production_files": "Legacy production-file count",
        "test_files": "Legacy test-file count",
        "generated_files": "Legacy generated-file count",
    }
    _BYTE_KEYS = {"inventoried_file_bytes", "size_bytes", "total_bytes"}
    _COUNT_KEYS = {
        "inventoried_file_count",
        "inventoried_files",
        "inventoried_file_size_error_count",
        "classified_non_test_source_files",
        "classified_test_source_files",
        "classified_generated_files",
        "production_files",
        "test_files",
        "generated_files",
    }

    def render(self, context: Mapping[str, object]) -> str:
        """Return deterministic Markdown for a compact repository context."""

        if not isinstance(context, Mapping):
            raise TypeError("repository report context must be a mapping")

        workspace = self._as_mapping(context.get("workspace"))
        summary = self._as_mapping(context.get("repository_summary"))
        repository_name = self._first_present(
            workspace,
            "repository_name",
            "name",
        )

        lines = [
            f"# Repository explanation: {self._display(repository_name)}",
            "",
            (
                "This report is rendered deterministically from source-free "
                "Atlas semantic metadata. An LLM did not create or alter its "
                "values or conclusions."
            ),
            "",
            "## Repository",
            "",
            "| Field | Value |",
            "| --- | --- |",
            self._table_row("Name", repository_name),
            self._table_row(
                "Root",
                self._first_present(workspace, "root", "repository_root"),
            ),
            self._table_row(
                "Discovered projects",
                self._first_present(
                    workspace,
                    "discovered_project_count",
                    "project_count",
                ),
            ),
        ]

        self._render_inventory(lines, summary)
        self._render_languages(lines, summary)
        self._render_build_systems(lines, summary.get("build_systems"))
        self._render_frameworks(
            lines,
            self._first_present(
                summary,
                "frameworks_and_related_technologies",
                "frameworks",
            ),
        )
        self._render_entry_points(
            lines,
            self._first_present(
                summary,
                "entry_point_candidates",
                "entry_points",
            ),
        )
        self._render_hierarchy(
            lines,
            self._first_present(
                summary,
                "filesystem_project_hierarchy",
                "module_hierarchy",
            ),
        )
        self._render_structured_section(
            lines,
            "Dependencies",
            self._dependencies(summary),
        )
        self._render_structured_section(
            lines,
            "Architecture",
            context.get("architecture"),
        )
        self._render_structured_section(
            lines,
            "Design patterns",
            context.get("design_patterns"),
        )
        self._render_structured_section(
            lines,
            "Reachability",
            context.get("reachability"),
        )
        self._render_structured_section(
            lines,
            "Risk and hotspots",
            context.get("risk_analysis"),
        )
        self._render_structured_section(
            lines,
            "Limitations",
            context.get("limitations"),
        )
        return "\n".join(lines).rstrip() + "\n"

    def _render_inventory(
        self,
        lines: list[str],
        summary: Mapping[str, object],
    ) -> None:
        inventory = self._as_mapping(summary.get("inventory"))
        measurements = self._as_mapping(inventory.get("measurements"))
        if not measurements:
            measurements = {
                key: summary[key]
                for key in self._INVENTORY_LABELS
                if key in summary and summary[key] is not None
            }
        lines.extend(["", "## Inventory", ""])
        if not measurements:
            lines.append("Unavailable in the supplied semantic context.")
            return
        lines.extend([
            "| Metric | Exact value | Unit | Definition |",
            "| --- | ---: | --- | --- |",
        ])
        ordered_keys = [
            key for key in self._INVENTORY_LABELS if key in measurements
        ]
        ordered_keys.extend(
            sorted(str(key) for key in measurements if key not in ordered_keys)
        )
        for key in ordered_keys:
            record = measurements.get(key)
            if isinstance(record, Mapping):
                value = record.get("value")
                unit = record.get("unit")
                definition = record.get("definition")
            else:
                value = record
                unit = "bytes" if key in self._BYTE_KEYS else "files"
                definition = None
            label = self._INVENTORY_LABELS.get(key, self._label(key))
            lines.append("| " + " | ".join((
                self._cell(label),
                self._cell(self._number(value) if self._is_number(value) else value),
                self._cell(unit),
                self._cell(definition),
            )) + " |")
        metadata = {
            key: item for key, item in inventory.items()
            if key not in {"measurements", "status"}
        }
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_languages(
        self,
        lines: list[str],
        summary: Mapping[str, object],
    ) -> None:
        value = self._first_present(
            summary,
            "language_distribution",
            "language_file_counts",
            "languages",
        )
        lines.extend(["", "## Language distribution", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return

        metadata: Mapping[str, object] = {}
        records: list[tuple[object, object, object, object]] = []
        if isinstance(value, Mapping):
            if self._is_sequence(value.get("items")):
                metadata = {
                    key: item for key, item in value.items()
                    if key != "items"
                }
                for item in value["items"]:
                    if isinstance(item, Mapping):
                        records.append((
                            self._first_present(item, "language", "name"),
                            self._first_present(item, "file_count", "count"),
                            self._language_share(item),
                            self._first_present(item, "status", "limitations", "note"),
                        ))
            else:
                records.extend((name, count, None, None) for name, count in value.items())
                records.sort(key=lambda item: str(item[0]).casefold())
        elif self._is_sequence(value):
            for item in value:
                if isinstance(item, Mapping):
                    records.append((
                        self._first_present(item, "language", "name"),
                        self._first_present(item, "file_count", "count"),
                        self._language_share(item),
                        self._first_present(item, "status", "limitations", "note"),
                    ))
                else:
                    records.append((item, None, None, None))
        else:
            records.append((value, None, None, None))

        lines.extend([
            "| Language | Inventoried files | File share | Status or limitation |",
            "| --- | ---: | ---: | --- |",
        ])
        for language, count, share, note in records:
            lines.append("| " + " | ".join((
                self._cell(language),
                self._cell(self._number(count) if self._is_number(count) else count),
                self._cell(share),
                self._cell("—" if note is None else note),
            )) + " |")
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_build_systems(
        self,
        lines: list[str],
        value: object,
    ) -> None:
        lines.extend(["", "## Build systems", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return
        mapping = self._as_mapping(value)
        records = mapping.get("items") if self._is_sequence(mapping.get("items")) else value
        if not self._is_sequence(records):
            records = [records]
        lines.extend([
            "| Name | Detected projects | Root-project inventory | Classification | Confidence |",
            "| --- | ---: | --- | --- | --- |",
        ])
        for record in records:
            if isinstance(record, Mapping):
                confidence = self._as_mapping(record.get("confidence")).get("status")
                lines.append("| " + " | ".join((
                    self._cell(record.get("name")),
                    self._cell(record.get("detected_project_count")),
                    self._cell(record.get("detected_in_root_project_inventory")),
                    self._cell(record.get("classification")),
                    self._cell(confidence),
                )) + " |")
            else:
                lines.append("| " + " | ".join((self._cell(record), "—", "—", "—", "—")) + " |")
        metadata = {
            key: item for key, item in mapping.items() if key != "items"
        }
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_frameworks(self, lines: list[str], value: object) -> None:
        lines.extend(["", "## Frameworks and related technologies", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return
        mapping = self._as_mapping(value)
        records = mapping.get("items") if self._is_sequence(mapping.get("items")) else value
        if not self._is_sequence(records):
            records = [records]
        lines.extend([
            "| Name | Classification | Adoption | Projects | Evidence | Scopes | Representative references | Confidence |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ])
        for record in records:
            if not isinstance(record, Mapping):
                lines.append("| " + " | ".join((self._cell(record), *("—",) * 7)) + " |")
                continue
            confidence = self._as_mapping(record.get("confidence")).get("status")
            scopes = ", ".join(map(str, record.get("evidence_scopes", ())))
            references = ", ".join(map(str, record.get("representative_references", ())))
            omitted = record.get("omitted_reference_count")
            if self._is_number(omitted) and omitted:
                references = f"{references} (+{self._number(omitted)} omitted)"
            lines.append("| " + " | ".join((
                self._cell(record.get("name")),
                self._cell(record.get("classification")),
                self._cell(record.get("adoption_status")),
                self._cell(record.get("project_count")),
                self._cell(record.get("evidence_count")),
                self._cell(scopes or "—"),
                self._cell(references or "—"),
                self._cell(confidence),
            )) + " |")
        metadata = {
            key: item for key, item in mapping.items() if key != "items"
        }
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_entry_points(self, lines: list[str], value: object) -> None:
        lines.extend(["", "## Entry-point candidates", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return
        mapping = self._as_mapping(value)
        records = mapping.get("items") if self._is_sequence(mapping.get("items")) else value
        if not self._is_sequence(records):
            records = [records]
        lines.extend([
            "| Project | Path | Candidate kind | Scope | Runtime role | Confidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for record in records:
            if not isinstance(record, Mapping):
                lines.append("| " + " | ".join((self._cell(record), *("—",) * 5)) + " |")
                continue
            confidence = self._as_mapping(record.get("confidence")).get("status")
            lines.append("| " + " | ".join((
                self._cell(record.get("project")),
                self._cell(record.get("path")),
                self._cell(record.get("candidate_kind")),
                self._cell(record.get("scope_candidate")),
                self._cell(record.get("runtime_role")),
                self._cell(confidence),
            )) + " |")
        metadata = {
            key: item for key, item in mapping.items() if key != "items"
        }
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_hierarchy(self, lines: list[str], value: object) -> None:
        lines.extend(["", "## Filesystem project hierarchy", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return
        mapping = self._as_mapping(value)
        records = mapping.get("representative_relationships")
        if not self._is_sequence(records):
            records = value if self._is_sequence(value) else []
        lines.extend([
            "| Project | Filesystem parent |",
            "| --- | --- |",
        ])
        for record in records:
            if isinstance(record, Mapping):
                lines.append("| " + " | ".join((
                    self._cell(record.get("project")),
                    self._cell(record.get("parent")),
                )) + " |")
            else:
                lines.append("| " + " | ".join((self._cell(record), "—")) + " |")
        metadata = {
            key: item for key, item in mapping.items()
            if key != "representative_relationships"
        }
        if metadata:
            self._append_value(lines, metadata, indent=0)

    def _render_structured_section(
        self,
        lines: list[str],
        title: str,
        value: object,
    ) -> None:
        lines.extend(["", f"## {title}", ""])
        if value is None or value == {} or value == [] or value == ():
            lines.append("Unavailable in the supplied semantic context.")
            return
        self._append_value(lines, value, indent=0)

    def _append_value(
        self,
        lines: list[str],
        value: object,
        *,
        indent: int,
    ) -> None:
        prefix = " " * indent
        if isinstance(value, Mapping):
            if not value:
                lines.append(f"{prefix}- No records supplied.")
                return
            for key in sorted(value, key=lambda item: str(item)):
                item = value[key]
                label = self._label(key)
                if self._is_container(item):
                    lines.append(f"{prefix}- **{self._escape(label)}:**")
                    self._append_value(lines, item, indent=indent + 2)
                else:
                    lines.append(
                        f"{prefix}- **{self._escape(label)}:** {self._display(item)}"
                    )
            return
        if self._is_sequence(value):
            if not value:
                lines.append(f"{prefix}- No records supplied.")
                return
            for item in value:
                if self._is_container(item):
                    lines.append(f"{prefix}-")
                    self._append_value(lines, item, indent=indent + 2)
                else:
                    lines.append(f"{prefix}- {self._display(item)}")
            return
        lines.append(f"{prefix}{self._display(value)}")

    @staticmethod
    def _dependencies(summary: Mapping[str, object]) -> object:
        direct = summary.get("dependencies")
        if direct is not None:
            return direct
        keys = (
            "declared_dependency_count_by_ecosystem",
            "total_declared_dependency_records",
            "dependency_manifest_count_by_ecosystem",
            "total_dependency_manifests",
        )
        result = {key: summary[key] for key in keys if key in summary}
        return result or None

    @classmethod
    def _language_share(cls, item: Mapping[str, object]) -> object:
        basis_points = cls._first_present(
            item,
            "basis_points",
            "percentage_basis_points",
        )
        if cls._is_number(basis_points):
            return f"{float(basis_points) / 100:.2f}% ({cls._number(basis_points)} bp)"
        percentage = cls._first_present(
            item,
            "file_share_percent",
            "percentage",
            "percent",
        )
        if cls._is_number(percentage):
            return f"{cls._number(percentage)}%"
        return percentage

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _first_present(mapping: Mapping[Any, object], *keys: str) -> object:
        for key in keys:
            if key in mapping and mapping[key] is not None:
                return mapping[key]
        return None

    @staticmethod
    def _is_sequence(value: object) -> bool:
        return isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        )

    @classmethod
    def _is_container(cls, value: object) -> bool:
        return isinstance(value, Mapping) or cls._is_sequence(value)

    @staticmethod
    def _is_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _number(value: object) -> str:
        if isinstance(value, int) and not isinstance(value, bool):
            return f"{value:,}"
        if isinstance(value, float):
            return format(value, ".12g")
        return str(value)

    @classmethod
    def _display(cls, value: object) -> str:
        if value is None:
            return "Unavailable"
        if isinstance(value, bool):
            return "true" if value else "false"
        if cls._is_number(value):
            return cls._number(value)
        return cls._escape(str(value))

    @classmethod
    def _cell(cls, value: object) -> str:
        return cls._display(value).replace("|", "\\|")

    @classmethod
    def _table_row(
        cls,
        label: object,
        value: object,
        *,
        value_is_rendered: bool = False,
    ) -> str:
        rendered = cls._escape(str(value)) if value_is_rendered else cls._display(value)
        return f"| {cls._cell(label)} | {rendered.replace('|', '\\|')} |"

    @staticmethod
    def _label(value: object) -> str:
        return str(value).replace("_", " ").strip().capitalize()

    @staticmethod
    def _escape(value: str) -> str:
        normalized = " ".join(value.replace("\x00", "").splitlines()).strip()
        escaped = escape_html(normalized, quote=False).replace("\\", "\\\\")
        for marker in ("`", "*", "_", "[", "]"):
            escaped = escaped.replace(marker, f"\\{marker}")
        return escaped
