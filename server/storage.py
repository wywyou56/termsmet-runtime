"""Shared SQLite storage. All writes must use transaction()."""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT NOT NULL PRIMARY KEY,
        buyer_identity TEXT NOT NULL DEFAULT 'buyer' CHECK (buyer_identity = 'buyer'),
        provider_identity TEXT NOT NULL DEFAULT 'provider' CHECK (provider_identity = 'provider'),
        current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version > 0),
        current_submission_version INTEGER NOT NULL DEFAULT 0 CHECK (current_submission_version >= 0),
        status TEXT NOT NULL CHECK (status IN (
            'PROPOSED', 'COUNTERED', 'ACCEPTED', 'FUNDED', 'SUBMITTED',
            'FAILED', 'CHECK_ERROR', 'IN_REVIEW', 'RELEASED', 'CANCELLED'
        )),
        first_submission_deadline TEXT,
        repair_deadline TEXT,
        review_deadline TEXT,
        recovery_deadline TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        accepted_at TEXT,
        funded_at TEXT,
        released_at TEXT,
        cancelled_at TEXT,
        cancellation_reason TEXT,
        provider_fault INTEGER CHECK (provider_fault IN (0, 1))
    )""",
    """CREATE TABLE IF NOT EXISTS agreement_versions (
        job_id TEXT NOT NULL REFERENCES jobs(job_id),
        version INTEGER NOT NULL CHECK (version > 0),
        terms_json TEXT NOT NULL,
        source_csv TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        checker_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (job_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS acceptances (
        job_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        identity TEXT NOT NULL CHECK (identity IN ('buyer', 'provider')),
        accepted_at TEXT NOT NULL,
        PRIMARY KEY (job_id, version, identity),
        FOREIGN KEY (job_id, version) REFERENCES agreement_versions(job_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS submissions (
        job_id TEXT NOT NULL,
        submission_version INTEGER NOT NULL CHECK (submission_version > 0),
        agreement_version INTEGER NOT NULL,
        delivery_json TEXT NOT NULL,
        submitted_by TEXT NOT NULL CHECK (submitted_by = 'provider'),
        submitted_at TEXT NOT NULL,
        response_deadline TEXT NOT NULL,
        PRIMARY KEY (job_id, submission_version),
        FOREIGN KEY (job_id, agreement_version) REFERENCES agreement_versions(job_id, version)
    )""",
    """CREATE TABLE IF NOT EXISTS check_results (
        job_id TEXT NOT NULL,
        submission_version INTEGER NOT NULL,
        source_hash TEXT NOT NULL,
        checker_version TEXT NOT NULL,
        verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL', 'UNKNOWN')),
        errors_json TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        PRIMARY KEY (job_id, submission_version),
        FOREIGN KEY (job_id, submission_version) REFERENCES submissions(job_id, submission_version)
    )""",
    """CREATE TABLE IF NOT EXISTS challenges (
        challenge_id TEXT NOT NULL PRIMARY KEY,
        job_id TEXT NOT NULL,
        submission_version INTEGER NOT NULL,
        identity TEXT NOT NULL CHECK (identity IN ('buyer', 'provider')),
        reason_code TEXT NOT NULL CHECK (reason_code IN (
            'SOURCE_MISMATCH', 'CHECKER_VERSION_MISMATCH', 'DISPUTE_FAIL'
        )),
        outcome TEXT NOT NULL CHECK (outcome IN ('ACCEPTED', 'REJECTED', 'RECORDED')),
        reason TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (job_id, submission_version) REFERENCES check_results(job_id, submission_version)
    )""",
    """CREATE TABLE IF NOT EXISTS settlement_events (
        job_id TEXT NOT NULL REFERENCES jobs(job_id),
        event_type TEXT NOT NULL CHECK (event_type IN (
            'SIMULATED_FUNDING', 'SIMULATED_RELEASE', 'SIMULATED_REFUND'
        )),
        simulated INTEGER NOT NULL CHECK (simulated = 1),
        created_at TEXT NOT NULL,
        PRIMARY KEY (job_id, event_type)
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS one_terminal_settlement
        ON settlement_events(job_id)
        WHERE event_type IN ('SIMULATED_RELEASE', 'SIMULATED_REFUND')""",
)


@contextmanager
def transaction(connection: sqlite3.Connection):
    """Serialize a state change across processes and roll back on failure."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        connection.rollback()
        raise


def _enable_wal(connection: sqlite3.Connection) -> None:
    # Switching a fresh database to WAL can return BUSY without honoring busy_timeout.
    deadline = time.monotonic() + 5
    connection.execute("PRAGMA busy_timeout = 0")
    try:
        while True:
            try:
                mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                break
            except sqlite3.OperationalError as exc:
                remaining = deadline - time.monotonic()
                if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY or remaining <= 0:
                    raise
                time.sleep(min(0.05, remaining))
    finally:
        connection.execute("PRAGMA busy_timeout = 5000")
    if mode.lower() != "wal":
        raise sqlite3.OperationalError("TermsMet requires SQLite WAL mode")


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _enable_wal(connection)
        with transaction(connection):
            for statement in SCHEMA:
                connection.execute(statement)
    except BaseException:
        connection.close()
        raise
    return connection
