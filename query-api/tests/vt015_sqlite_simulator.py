"""SIMULATED OpenSearch client surface using isolated SQLite unique inserts.

This exercises ApprovalRepository with real transactional persistence, but does
not model OpenSearch transport, shards, refresh, replication or durability.
"""
import json
import sqlite3
from contextlib import closing

from opensearchpy.exceptions import ConflictError, NotFoundError


class SQLiteApprovalClient:
    def __init__(self, path, index):
        if not index.startswith("vt015-sim-"):
            raise ValueError("Only isolated simulator indexes are allowed")
        self.path, self.index_name = str(path), index
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS approvals ("
                               "index_name TEXT, cluster_id TEXT, document TEXT NOT NULL, "
                               "PRIMARY KEY (index_name, cluster_id))")
            connection.commit()

    def _check(self, index):
        if index != self.index_name:
            raise ValueError("Index outside this isolated simulation")

    def create(self, *, index, id, body, refresh):
        self._check(index)
        try:
            with closing(sqlite3.connect(self.path, timeout=30)) as connection:
                with connection:
                    connection.execute("INSERT INTO approvals VALUES (?, ?, ?)",
                                       (index, id, json.dumps(body)))
        except sqlite3.IntegrityError:
            raise ConflictError(409, "version_conflict_engine_exception") from None
        return {"result": "created"}

    def get(self, *, index, id):
        self._check(index)
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            row = connection.execute("SELECT document FROM approvals WHERE "
                                     "index_name=? AND cluster_id=?", (index, id)).fetchone()
        if row is None:
            raise NotFoundError(404, "not_found")
        return {"found": True, "_source": json.loads(row[0])}

    def documents(self):
        with closing(sqlite3.connect(self.path, timeout=30)) as connection:
            rows = connection.execute("SELECT document FROM approvals WHERE index_name=?",
                                      (self.index_name,)).fetchall()
        return [json.loads(row[0]) for row in rows]
