"""Run-local, source-free filesystem operation accounting."""

from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
import hashlib
import os
from os import PathLike
from threading import RLock

from .models import (
    FILESYSTEM_COUNTERS,
    FilesystemConsumerOverlap,
    FilesystemConsumerMetrics,
    FilesystemLedgerSnapshot,
    stable_identifier,
)


class FilesystemOperation(StrEnum):
    DIRECTORY_ENUMERATION = "directory_enumerations"
    METADATA_LOOKUP = "metadata_lookups"
    PATH_NORMALIZATION = "path_normalizations"
    CONTENT_READ = "content_reads"
    HASH = "hashes"
    DESCRIPTOR_PARSE = "descriptor_parses"
    LANGUAGE_PARSE = "language_parses"


class FilesystemLedger:
    """Thread-safe counters that exist only for the lifetime of one run.

    File-aware methods use a path transiently and retain only a one-way digest until
    the run ends.  Neither that digest nor a path enters the immutable report.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        resource_limit: int = 100_000,
    ) -> None:
        if (
            not isinstance(resource_limit, int)
            or isinstance(resource_limit, bool)
            or resource_limit < 1
        ):
            raise ValueError("filesystem resource limit must be a positive integer")
        self._enabled = enabled
        self._resource_limit = resource_limit
        self._values: dict[str, dict[str, int]] = defaultdict(
            lambda: {name: 0 for name in FILESYSTEM_COUNTERS}
        )
        self._content_resources: dict[bytes, dict[str, int]] = defaultdict(dict)
        self._resource_tracking_saturated = False
        self._untracked_content_reads = 0
        self._lock = RLock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def record(
        self,
        operation: FilesystemOperation,
        *,
        consumer: str,
        count: int = 1,
        bytes_read: int | None = 0,
    ) -> None:
        if not self._enabled:
            return
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("filesystem operation count must be non-negative")
        if (
            bytes_read is not None
            and (
                not isinstance(bytes_read, int)
                or isinstance(bytes_read, bool)
                or bytes_read < 0
            )
        ):
            raise ValueError("filesystem bytes read must be non-negative")
        normalized = stable_identifier(consumer, label="filesystem consumer")
        normalized_operation = FilesystemOperation(operation)
        if bytes_read is None and normalized_operation is not FilesystemOperation.CONTENT_READ:
            raise ValueError("unavailable bytes are valid only for content reads")
        if bytes_read and normalized_operation is not FilesystemOperation.CONTENT_READ:
            raise ValueError("bytes_read is valid only for content reads")
        if (
            normalized_operation is FilesystemOperation.CONTENT_READ
            and count == 0
            and bytes_read not in {None, 0}
        ):
            raise ValueError("bytes_read requires at least one content read")
        field = normalized_operation.value
        with self._lock:
            self._values[normalized][field] += count
            # Identity-free reads cannot contribute to the source-free repeat-I/O
            # index.  Preserve that limitation explicitly instead of presenting
            # an incomplete index as measured coverage.
            if normalized_operation is FilesystemOperation.CONTENT_READ:
                self._untracked_content_reads += count
            if bytes_read is None:
                self._values[normalized]["content_read_bytes_unavailable"] += count
            elif bytes_read:
                self._values[normalized]["bytes_read"] += bytes_read

    def directory_enumerated(self, consumer: str, *, count: int = 1) -> None:
        self.record(
            FilesystemOperation.DIRECTORY_ENUMERATION,
            consumer=consumer,
            count=count,
        )

    def metadata_looked_up(self, consumer: str, *, count: int = 1) -> None:
        self.record(FilesystemOperation.METADATA_LOOKUP, consumer=consumer, count=count)

    def path_normalized(self, consumer: str, *, count: int = 1) -> None:
        self.record(FilesystemOperation.PATH_NORMALIZATION, consumer=consumer, count=count)

    def content_read(
        self,
        consumer: str,
        *,
        bytes_read: int | None,
        count: int = 1,
    ) -> None:
        self.record(
            FilesystemOperation.CONTENT_READ,
            consumer=consumer,
            count=count,
            bytes_read=bytes_read,
        )

    def file_content_read(
        self,
        consumer: str,
        path: str | PathLike[str],
    ) -> int | None:
        """Record one successful file read using its physical size when available.

        The path is used only for a run-local metadata lookup and is never stored.
        This avoids re-encoding a decoded source string merely to estimate I/O.
        """

        if not self._enabled:
            return None
        normalized = stable_identifier(consumer, label="filesystem consumer")
        try:
            size = os.stat(path).st_size
        except OSError:
            size = None
        if self._record_if_resource_tracking_saturated(
            normalized,
            bytes_read=size,
            measurement_metadata_lookup=True,
        ):
            return size
        identity = hashlib.sha256(
            os.fsencode(os.path.normcase(os.path.abspath(os.fspath(path))))
        ).digest()
        with self._lock:
            self._record_file_content_read(
                normalized,
                identity,
                bytes_read=size,
                measurement_metadata_lookup=True,
            )
        return size

    def file_content_read_known_size(
        self,
        consumer: str,
        path: str | PathLike[str],
        *,
        bytes_read: int,
    ) -> None:
        """Record an identity-aware read when the caller already has exact bytes."""

        if not self._enabled:
            return
        if (
            not isinstance(bytes_read, int)
            or isinstance(bytes_read, bool)
            or bytes_read < 0
        ):
            raise ValueError("filesystem bytes read must be non-negative")
        normalized = stable_identifier(consumer, label="filesystem consumer")
        if self._record_if_resource_tracking_saturated(
            normalized,
            bytes_read=bytes_read,
            measurement_metadata_lookup=False,
        ):
            return
        identity = hashlib.sha256(
            os.fsencode(os.path.normcase(os.path.abspath(os.fspath(path))))
        ).digest()
        with self._lock:
            self._record_file_content_read(
                normalized,
                identity,
                bytes_read=bytes_read,
                measurement_metadata_lookup=False,
            )

    def file_content_read_unknown_size(
        self,
        consumer: str,
        path: str | PathLike[str],
    ) -> None:
        """Record an identity-aware read without adding a metadata probe."""

        if not self._enabled:
            return
        normalized = stable_identifier(consumer, label="filesystem consumer")
        if self._record_if_resource_tracking_saturated(
            normalized,
            bytes_read=None,
            measurement_metadata_lookup=False,
        ):
            return
        identity = hashlib.sha256(
            os.fsencode(os.path.normcase(os.path.abspath(os.fspath(path))))
        ).digest()
        with self._lock:
            self._record_file_content_read(
                normalized,
                identity,
                bytes_read=None,
                measurement_metadata_lookup=False,
            )

    def _record_file_content_read(
        self,
        consumer: str,
        identity: bytes,
        *,
        bytes_read: int | None,
        measurement_metadata_lookup: bool,
    ) -> None:
        counters = self._values[consumer]
        if measurement_metadata_lookup:
            counters["measurement_metadata_lookups"] += 1
        counters[FilesystemOperation.CONTENT_READ.value] += 1
        if bytes_read is None:
            counters["content_read_bytes_unavailable"] += 1
        else:
            counters["bytes_read"] += bytes_read
        readers = self._content_resources.get(identity)
        if readers is None:
            if len(self._content_resources) >= self._resource_limit:
                self._resource_tracking_saturated = True
                self._untracked_content_reads += 1
                return
            readers = {}
            self._content_resources[identity] = readers
        readers[consumer] = readers.get(consumer, 0) + 1
        if len(self._content_resources) >= self._resource_limit:
            self._resource_tracking_saturated = True

    def _record_if_resource_tracking_saturated(
        self,
        consumer: str,
        *,
        bytes_read: int | None,
        measurement_metadata_lookup: bool,
    ) -> bool:
        with self._lock:
            if not self._resource_tracking_saturated:
                return False
            counters = self._values[consumer]
            if measurement_metadata_lookup:
                counters["measurement_metadata_lookups"] += 1
            counters[FilesystemOperation.CONTENT_READ.value] += 1
            if bytes_read is None:
                counters["content_read_bytes_unavailable"] += 1
            else:
                counters["bytes_read"] += bytes_read
            self._untracked_content_reads += 1
            return True

    def content_hashed(self, consumer: str, *, count: int = 1) -> None:
        self.record(FilesystemOperation.HASH, consumer=consumer, count=count)

    def descriptor_parsed(self, consumer: str, *, count: int = 1) -> None:
        self.record(FilesystemOperation.DESCRIPTOR_PARSE, consumer=consumer, count=count)

    def language_parsed(self, consumer: str, *, count: int = 1) -> None:
        self.record(FilesystemOperation.LANGUAGE_PARSE, consumer=consumer, count=count)

    def snapshot(self) -> FilesystemLedgerSnapshot:
        with self._lock:
            values = {
                consumer: dict(counters)
                for consumer, counters in self._values.items()
            }
            resources = {
                identity: dict(readers)
                for identity, readers in self._content_resources.items()
            }
            resource_limit_reached = self._resource_tracking_saturated
            untracked_content_reads = self._untracked_content_reads
        for consumer in {
            consumer
            for readers in resources.values()
            for consumer in readers
        }:
            counters = values.setdefault(
                consumer,
                {name: 0 for name in FILESYSTEM_COUNTERS},
            )
            consumer_reads = [
                readers[consumer]
                for readers in resources.values()
                if consumer in readers
            ]
            counters["consumer_unique_content_resources"] = len(consumer_reads)
            counters["consumer_repeated_content_reads"] = sum(
                max(0, count - 1) for count in consumer_reads
            )
        overlaps: dict[tuple[str, str], int] = defaultdict(int)
        for readers in resources.values():
            consumers = sorted(readers)
            for index, left in enumerate(consumers):
                for right in consumers[index + 1:]:
                    overlaps[(left, right)] += 1
        observed_reads = sum(
            count
            for readers in resources.values()
            for count in readers.values()
        )
        return FilesystemLedgerSnapshot(
            consumers=tuple(
                FilesystemConsumerMetrics(consumer=consumer, **counters)
                for consumer, counters in values.items()
            ),
            observed_unique_content_resources=len(resources),
            observed_content_reads=observed_reads,
            overlaps=tuple(
                FilesystemConsumerOverlap(pair, count)
                for pair, count in overlaps.items()
            ),
            coverage_status="partial" if self._enabled else "unavailable",
            coverage_reason=(
                "explicit-instrumentation-boundaries"
                if self._enabled
                else "collection-disabled"
            ),
            resource_tracking_limit=self._resource_limit,
            resource_limit_reached=resource_limit_reached,
            untracked_content_reads=untracked_content_reads,
        )

    def clear(self) -> int:
        """Discard run-local counters and return their total operation count."""

        with self._lock:
            total = sum(
                value
                for counters in self._values.values()
                for name, value in counters.items()
                if name not in {
                    "bytes_read",
                    "content_read_bytes_unavailable",
                    "consumer_unique_content_resources",
                    "consumer_repeated_content_reads",
                }
            )
            self._values.clear()
            self._content_resources.clear()
            self._resource_tracking_saturated = False
            self._untracked_content_reads = 0
            return total
