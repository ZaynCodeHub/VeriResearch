"""Run persistence.

Two backends behind one interface:

- `InMemoryRunStore` — a dict behind a lock. This is what every test and local
  `pytest`/`demo_verifier.py` run uses; no external service required. Runs
  vanish on process restart and it doesn't scale past one process, same as
  before this module existed.
- `PostgresRunStore` — the same shape backed by a `runs` table. Used whenever
  `DATABASE_URL` is set (i.e. in any real deployment), so runs survive
  restarts and multiple API instances can share state.

`RunState` is a pydantic-validated TypedDict (every value inside it is a
plain type or a pydantic model), so a `TypeAdapter(RunState)` round-trips the
whole thing to/from JSON without a hand-maintained schema — that's what each
backend stores in `state` / the `state` column.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

from pydantic import TypeAdapter

from .state import RunState

_STATE_ADAPTER: TypeAdapter = TypeAdapter(RunState)


@dataclass
class RunRecord:
    run_id: str
    topic: str
    mode: str
    status: str = "queued"  # queued | running | done | error
    state: Optional[RunState] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunStore(Protocol):
    def create(self, run_id: str, topic: str, mode: str) -> RunRecord: ...
    def get(self, run_id: str) -> Optional[RunRecord]: ...
    def list(self) -> list[RunRecord]: ...
    def mark_running(self, run_id: str) -> None: ...
    def mark_done(self, run_id: str, state: RunState) -> None: ...
    def mark_error(self, run_id: str, error: str) -> None: ...
    def count_in_flight(self) -> int: ...


class InMemoryRunStore:
    """Original behaviour: a dict behind a lock. Default backend, used by tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunRecord] = {}

    def create(self, run_id: str, topic: str, mode: str) -> RunRecord:
        record = RunRecord(run_id=run_id, topic=topic, mode=mode)
        with self._lock:
            self._runs[run_id] = record
        return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        with self._lock:
            return self._runs.get(run_id)

    def list(self) -> list[RunRecord]:
        with self._lock:
            return list(self._runs.values())

    def mark_running(self, run_id: str) -> None:
        with self._lock:
            self._runs[run_id].status = "running"

    def mark_done(self, run_id: str, state: RunState) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.state = state
            record.status = "done"

    def mark_error(self, run_id: str, error: str) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.status = "error"
            record.error = error

    def count_in_flight(self) -> int:
        with self._lock:
            return sum(1 for r in self._runs.values() if r.status in ("queued", "running"))


class PostgresRunStore:
    """Postgres-backed store, one row per run, `state` stored as JSONB.

    Uses a small connection pool (psycopg's `ConnectionPool`) rather than one
    connection per call — the API serves concurrent requests from a
    threadpool (FastAPI's `BackgroundTasks` + sync path handlers), so a
    single shared connection would serialize everything behind one socket.
    """

    def __init__(self, database_url: str) -> None:
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(database_url, min_size=1, max_size=10, open=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS runs_created_at_idx ON runs (created_at DESC)")

    @staticmethod
    def _row_to_record(row: tuple) -> RunRecord:
        # psycopg decodes jsonb columns into plain Python dict/list already,
        # so this is `validate_python`, not `validate_json`.
        run_id, topic, mode, status, state_obj, error, created_at = row
        return RunRecord(
            run_id=run_id,
            topic=topic,
            mode=mode,
            status=status,
            state=_STATE_ADAPTER.validate_python(state_obj) if state_obj is not None else None,
            error=error,
            created_at=created_at.isoformat(),
        )

    def create(self, run_id: str, topic: str, mode: str) -> RunRecord:
        record = RunRecord(run_id=run_id, topic=topic, mode=mode)
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, topic, mode, status, state, error, created_at) "
                "VALUES (%s, %s, %s, %s, NULL, NULL, %s)",
                (run_id, topic, mode, record.status, record.created_at),
            )
        return record

    def get(self, run_id: str) -> Optional[RunRecord]:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT run_id, topic, mode, status, state, error, created_at FROM runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list(self) -> list[RunRecord]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT run_id, topic, mode, status, state, error, created_at "
                "FROM runs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def mark_running(self, run_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("UPDATE runs SET status = 'running' WHERE run_id = %s", (run_id,))

    def mark_done(self, run_id: str, state: RunState) -> None:
        from psycopg.types.json import Jsonb

        state_obj = _STATE_ADAPTER.dump_python(state, mode="json")
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE runs SET status = 'done', state = %s WHERE run_id = %s",
                (Jsonb(state_obj), run_id),
            )

    def mark_error(self, run_id: str, error: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE runs SET status = 'error', error = %s WHERE run_id = %s",
                (error, run_id),
            )

    def count_in_flight(self) -> int:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT count(*) FROM runs WHERE status IN ('queued', 'running')"
            ).fetchone()
        return row[0]


def build_run_store() -> RunStore:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return PostgresRunStore(database_url)
    return InMemoryRunStore()
