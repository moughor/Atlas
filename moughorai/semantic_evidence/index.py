from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import EvidenceRecord


class EvidenceIndex:
    SCHEMA_VERSION = 1

    def __init__(
        self,
        records: Iterable[EvidenceRecord] = (),
        *,
        frozen: bool = False,
    ) -> None:
        self._records: dict[str, EvidenceRecord] = {}
        self._frozen = False
        for record in records:
            self.add(record)
        self._frozen = frozen

    def add(self, record: EvidenceRecord) -> str:
        if self._frozen:
            raise TypeError("frozen evidence indexes cannot be modified")
        existing = self._records.get(record.evidence_id)
        if existing is not None and existing != record:
            raise ValueError(f"conflicting evidence record: {record.evidence_id}")
        self._records[record.evidence_id] = record
        return record.evidence_id

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        return self._records.get(evidence_id)

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(sorted(self._records.values()))

    def __len__(self) -> int:
        return len(self._records)

    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> EvidenceIndex:
        """Return an immutable index suitable for cached public reports."""

        return self if self._frozen else EvidenceIndex(self.records, frozen=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvidenceIndex:
        if int(value.get("schema_version", 1)) != cls.SCHEMA_VERSION:
            raise ValueError("unsupported evidence index schema")
        return cls(
            EvidenceRecord.from_dict(item)
            for item in value.get("records", ())
            if isinstance(item, Mapping)
        )
