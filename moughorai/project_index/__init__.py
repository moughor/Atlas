"""Persistent, content-addressed project file index."""
from moughorai.project_index.indexer import ProjectFileIndexer
from moughorai.project_index.models import IndexedFile, IndexChangeSet, ProjectIndexSnapshot
from moughorai.project_index.service import PersistentProjectIndex
from moughorai.project_index.store import ProjectIndexStore

__all__ = [
    "IndexedFile",
    "IndexChangeSet",
    "PersistentProjectIndex",
    "ProjectFileIndexer",
    "ProjectIndexSnapshot",
    "ProjectIndexStore",
]
