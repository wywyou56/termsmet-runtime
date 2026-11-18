"""TermsMet business rules; no MCP or Hermes dependencies."""

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from . import checker
from .checker import CHECKER_VERSION, TEMPLATE_ID, MissingSourceColumnsError, list_templates, parse_source
from .storage import transaction


PERMISSIONS = {
    "list_templates": {"buyer", "provider"},
    "propose_agreement": {"buyer"},
    "list_jobs": {"buyer", "provider"},
    "get_job": {"buyer", "provider"},
    "counter_agreement": {"provider"},
    "accept_agreement": {"buyer", "provider"},
    "fund_job": {"buyer"},
    "submit_delivery": {"provider"},
    "get_result": {"buyer", "provider"},
    "challenge_result": {"buyer", "provider"},
    "retrieve_delivery": {"buyer"},
}
FIRST_SUBMISSION_EXPIRED = "FIRST_SUBMISSION_DEADLINE_PASSED"
REPAIR_EXPIRED = "REPAIR_DEADLINE_PASSED"
CHECK_ERROR_EXPIRED = "CHECK_ERROR_DEADLINE_PASSED"
DISPUTED_FAIL = "DISPUTED_FAIL"
logger = logging.getLogger(__name__)


def timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class BusinessError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details


class TermsMetService:
    def __init__(self, connection: sqlite3.Connection, identity: str,
                 first_submit_minutes: float = 5, clock=None, review_seconds: float = 10):
        if identity not in ("buyer", "provider"):
            raise ValueError("TERMSMET_IDENTITY must be buyer or provider")
        for attribute, name, seconds in (
            ("first_submit_window", "TERMSMET_FIRST_SUBMIT_MIN", first_submit_minutes * 60),
            ("review_window", "TERMSMET_REVIEW_SECONDS", review_seconds),
        ):
            try:
                window = timedelta(seconds=seconds)
                if window <= timedelta(0):
                    raise ValueError
                datetime.now(UTC) + window
            except (OverflowError, ValueError):
                raise ValueError(f"{name} must produce a positive, representable deadline") from None
            setattr(self, attribute, window)
        self.connection = connection
        self.identity = identity
        self.clock = clock if clock is not None else lambda: datetime.now(UTC)

    def call(self, tool_name: str, **arguments) -> dict[str, object]:
        if tool_name not in PERMISSIONS:
            raise ValueError("unsupported service action")
        if (self.identity not in PERMISSIONS[tool_name]
                or (tool_name == "challenge_result" and arguments.get("reason_code") == "DISPUTE_FAIL"
                    and self.identity != "provider")):
            return {"error": {"code": "PERMISSION_DENIED", "message": f"{tool_name} is not permitted for this caller"}}

        with transaction(self.connection):
            now = self.clock()
            admission = None
            if tool_name == "challenge_result" and isinstance(arguments.get("job_id"), str):
                # Automatic recovery must not erase a challenge's timely admission state.
                admission = self.connection.execute(
                    "SELECT * FROM jobs WHERE job_id = ?", (arguments["job_id"],)
                ).fetchone()
            events = self.advance_due_jobs(now)
            self.connection.execute("SAVEPOINT requested_action")
            try:
                if tool_name == "challenge_result":
                    result = self._challenge_result(now, admission, **arguments)
                else:
                    result = getattr(self, f"_{tool_name}")(now, **arguments)
            except BusinessError as exc:
                self.connection.execute("ROLLBACK TO requested_action")
                result = {"error": {"code": exc.code, "message": str(exc)}}
                if exc.details is not None:
                    result["error"]["details"] = exc.details
            self.connection.execute("RELEASE requested_action")

        for event_type, job_id in events:
            logger.info("%s job_id=%s simulated=true", event_type, job_id)
        if tool_name == "fund_job" and "error" not in result:
            logger.info("SIMULATED_FUNDING confirmed job_id=%s simulated=true", result["job_id"])
        return result

    def advance_due_jobs(self, now: datetime) -> list[tuple[str, str]]:
        """Advance deadlines and settlement while holding the write transaction."""
        events = []
        for job in self.connection.execute(
            "SELECT * FROM jobs WHERE status IN ('FUNDED', 'FAILED', 'CHECK_ERROR', 'IN_REVIEW')"
        ).fetchall():
            if job["status"] == "FAILED":
                agreement = self._agreement(job)
                if not self._valid_result(job, agreement, self._result(job["job_id"], job["current_submission_version"])):
                    self._enter_check_error(job, now)
                else:
                    _, repair = self._repair_history(job, agreement)
                    if repair != job["repair_deadline"]:
                        self.connection.execute(
                            "UPDATE jobs SET repair_deadline = ?, updated_at = ? WHERE job_id = ?",
                            (repair, timestamp(now), job["job_id"]),
                        )
                job = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
            if job["status"] == "IN_REVIEW":
                if not self._passing_evidence(job):
                    self._enter_check_error(job, now)
                    job = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job["job_id"],)).fetchone()
                elif now >= datetime.fromisoformat(job["review_deadline"]):
                    if not self._release_authorized(job):
                        continue
                    self._write_settlement(job["job_id"], "SIMULATED_RELEASE", now)
                    self.connection.execute(
                        "UPDATE jobs SET status = 'RELEASED', released_at = ?, updated_at = ? WHERE job_id = ?",
                        (timestamp(now), timestamp(now), job["job_id"]),
                    )
                    events.append(("SIMULATED_RELEASE", job["job_id"]))
                    continue
                else:
                    continue
            if job["status"] == "FUNDED" and (job["current_submission_version"] != 0 or self.connection.execute(
                "SELECT 1 FROM submissions WHERE job_id = ?", (job["job_id"],)
            ).fetchone()):
                continue
            deadline, reason, fault = {
                "FUNDED": ("first_submission_deadline", FIRST_SUBMISSION_EXPIRED, True),
                "FAILED": ("repair_deadline", REPAIR_EXPIRED, True),
                "CHECK_ERROR": ("recovery_deadline", CHECK_ERROR_EXPIRED, False),
            }[job["status"]]
            if now >= datetime.fromisoformat(job[deadline]):
                if job["status"] == "FAILED" and self._unresolved_dispute(job):
                    reason, fault = DISPUTED_FAIL, False
                if self._cancel(job, now, reason, fault):
                    events.append(("SIMULATED_REFUND", job["job_id"]))
        return events

    def _release_authorized(self, job: sqlite3.Row) -> bool:
        return True

    def _has_event(self, job_id: str, event_type: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM settlement_events WHERE job_id = ? AND event_type = ? AND simulated = 1",
            (job_id, event_type),
        ).fetchone() is not None

    def _cancel(self, job: sqlite3.Row, now: datetime, reason: str, fault: bool) -> bool:
        funded = self._has_event(job["job_id"], "SIMULATED_FUNDING")
        if funded:
            self._write_settlement(job["job_id"], "SIMULATED_REFUND", now)
        self.connection.execute(
            """UPDATE jobs SET status = 'CANCELLED', cancelled_at = ?, updated_at = ?,
               cancellation_reason = ?, provider_fault = ? WHERE job_id = ?""",
            (timestamp(now), timestamp(now), reason, int(fault), job["job_id"]),
        )
        return funded

    def _enter_check_error(self, job: sqlite3.Row, now: datetime) -> None:
        submission = self.connection.execute(
            "SELECT response_deadline FROM submissions WHERE job_id = ? AND submission_version = ?",
            (job["job_id"], job["current_submission_version"]),
        ).fetchone()
        deadline = submission[0] if submission else job["first_submission_deadline"] or timestamp(now)
        self.connection.execute(
            "UPDATE jobs SET status = 'CHECK_ERROR', recovery_deadline = ?, updated_at = ? WHERE job_id = ?",
            (deadline, timestamp(now), job["job_id"]),
        )

    def _valid_result(self, job: sqlite3.Row, agreement: sqlite3.Row, result: sqlite3.Row | None) -> bool:
        """Conclusive, compatible evidence; FAIL is valid evidence too."""
        if (agreement is None or result is None or result["verdict"] not in ("PASS", "FAIL")
                or result["agreement_version"] != job["current_version"]
                or result["source_hash"] != agreement["source_hash"]
                or agreement["source_hash"] != hashlib.sha256(agreement["source_csv"].encode("utf-8")).hexdigest()
                or result["checker_version"] != agreement["checker_version"]):
            return False
        return self.connection.execute(
            "SELECT 1 FROM challenges WHERE job_id = ? AND submission_version = ? AND outcome = 'ACCEPTED'",
            (job["job_id"], result["submission_version"]),
        ).fetchone() is None

    def _conclusive_results(self, job: sqlite3.Row) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT s.agreement_version, r.* FROM submissions s JOIN check_results r
               USING (job_id, submission_version) WHERE s.job_id = ? AND s.agreement_version = ?
               AND r.verdict IN ('PASS', 'FAIL') ORDER BY submission_version""",
            (job["job_id"], job["current_version"]),
        ).fetchall()

    def _repair_history(self, job: sqlite3.Row, agreement: sqlite3.Row) -> tuple[int, str | None]:
        used, deadline = 0, None
        for result in self._conclusive_results(job):
            if not self._valid_result(job, agreement, result):
                continue
            if deadline is not None:
                used += 1
            elif result["verdict"] == "FAIL":
                minutes = json.loads(agreement["terms_json"])["repair_window_minutes"]
                deadline = timestamp(datetime.fromisoformat(result["checked_at"]) + timedelta(minutes=minutes))
        return used, deadline

    def _unresolved_dispute(self, job: sqlite3.Row) -> bool:
        disputed = {row[0] for row in self.connection.execute(
            """SELECT submission_version FROM challenges WHERE job_id = ? AND identity = 'provider'
               AND reason_code = 'DISPUTE_FAIL' AND outcome = 'RECORDED'""", (job["job_id"],)
        )}
        if not disputed:
            return False
        agreement = self._agreement(job)
        for result in reversed(self._conclusive_results(job)):
            if not self._valid_result(job, agreement, result):
                continue
            if result["verdict"] == "PASS":
                return False
            if result["submission_version"] in disputed:
                return True
        return False

    def _passing_evidence(self, job: sqlite3.Row) -> bool:
        agreement = self._agreement(job)
        result = self._result(job["job_id"], job["current_submission_version"])
        if (not self._valid_result(job, agreement, result) or result["verdict"] != "PASS"
                or self._accepted_by(job) != ["buyer", "provider"]
                or not self._has_event(job["job_id"], "SIMULATED_FUNDING")
                or self._has_event(job["job_id"], "SIMULATED_REFUND")):
            return False
        try:
            return (json.loads(result["errors_json"]) == []
                    and datetime.fromisoformat(job["review_deadline"]) >= datetime.fromisoformat(result["checked_at"]))
        except (ValueError, TypeError):
            return False

    def _release_allowed(self, job: sqlite3.Row, submission_version: int, now: datetime) -> bool:
        return (job["status"] == "RELEASED" and job["current_submission_version"] == submission_version
                and self._passing_evidence(job) and now >= datetime.fromisoformat(job["review_deadline"])
                and self._has_event(job["job_id"], "SIMULATED_RELEASE"))

    def _write_settlement(self, job_id: str, event_type: str, now: datetime) -> None:
        self.connection.execute(
            """INSERT INTO settlement_events (job_id, event_type, simulated, created_at)
               VALUES (?, ?, 1, ?) ON CONFLICT (job_id, event_type) DO NOTHING""",
            (job_id, event_type, timestamp(now)),
        )

    def _job(self, job_id: str) -> sqlite3.Row:
        if not isinstance(job_id, str) or not job_id:
            raise BusinessError("INVALID_TERMS", "job_id must be a nonempty string")
        job = self.connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise BusinessError("NOT_FOUND", "job not found")
        if self.identity not in (job["buyer_identity"], job["provider_identity"]):
            raise BusinessError("PERMISSION_DENIED", "caller is not a party to this job")
        return job

    def _agreement(self, job: sqlite3.Row) -> sqlite3.Row:
        return self.connection.execute(
            "SELECT * FROM agreement_versions WHERE job_id = ? AND version = ?",
            (job["job_id"], job["current_version"]),
        ).fetchone()

    def _result(self, job_id: str, submission_version: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """SELECT s.agreement_version, r.* FROM submissions s JOIN check_results r
               USING (job_id, submission_version) WHERE s.job_id = ? AND s.submission_version = ?""",
            (job_id, submission_version),
        ).fetchone()

    def _accepted_by(self, job: sqlite3.Row) -> list[str]:
        return [row[0] for row in self.connection.execute(
            "SELECT identity FROM acceptances WHERE job_id = ? AND version = ? ORDER BY identity",
            (job["job_id"], job["current_version"]),
        )]

    def _list_templates(self, now: datetime) -> dict[str, object]:
        return list_templates()

    def _propose_agreement(self, now: datetime, template_id: str, source_csv: str) -> dict[str, object]:
        if template_id != TEMPLATE_ID:
            raise BusinessError("INVALID_TERMS", "unsupported template_id")
        try:
            parse_source(source_csv)
            source_hash = hashlib.sha256(source_csv.encode("utf-8")).hexdigest()
        except MissingSourceColumnsError as exc:
            raise BusinessError("INVALID_TERMS", str(exc), details=exc.details) from exc
        except ValueError as exc:
            raise BusinessError("INVALID_TERMS", "source_csv must contain valid, unambiguous order data") from exc
        job_id = f"job-{uuid4().hex}"
        terms = {
            "template_id": TEMPLATE_ID, "source_csv": source_csv,
            "repair_window_minutes": 5, "max_repairs": 1,
        }
        self.connection.execute(
            "INSERT INTO jobs (job_id, status, created_at, updated_at) VALUES (?, 'PROPOSED', ?, ?)",
            (job_id, timestamp(now), timestamp(now)),
        )
        self.connection.execute(
            """INSERT INTO agreement_versions
               (job_id, version, terms_json, source_csv, source_hash, checker_version, created_at)
               VALUES (?, 1, ?, ?, ?, ?, ?)""",
            (job_id, json.dumps(terms), source_csv, source_hash, CHECKER_VERSION, timestamp(now)),
        )
        return {"job_id": job_id, "version": 1, "status": "PROPOSED",
                "source_hash": source_hash, "checker_version": CHECKER_VERSION}

    def _list_jobs(self, now: datetime) -> dict[str, object]:
        jobs = self.connection.execute(
            """SELECT j.job_id, j.status, j.current_version,
               EXISTS (SELECT 1 FROM acceptances a WHERE a.job_id = j.job_id
                       AND a.version = j.current_version AND a.identity = ?) AS your_acceptance
               FROM jobs j WHERE j.buyer_identity = ? OR j.provider_identity = ?
               ORDER BY j.created_at, j.job_id""",
            (self.identity, self.identity, self.identity),
        )
        return {"jobs": [{"job_id": row["job_id"], "status": row["status"],
                          "current_version": row["current_version"], "your_acceptance": bool(row["your_acceptance"])}
                         for row in jobs]}

    def _get_job(self, now: datetime, job_id: str) -> dict[str, object]:
        job = self._job(job_id)
        agreement = self._agreement(job)
        deadlines = {name: job[column] for name, column in (
            ("first_submission", "first_submission_deadline"), ("repair", "repair_deadline"),
            ("review", "review_deadline"), ("recovery", "recovery_deadline"),
        ) if job[column] is not None}
        return {"job_id": job_id, "status": job["status"], "version": job["current_version"],
                "current_submission_version": job["current_submission_version"],
                "terms": json.loads(agreement["terms_json"]), "source_csv": agreement["source_csv"],
                "deadlines": deadlines}

    def _counter_agreement(self, now: datetime, job_id: str, repair_window_minutes: int) -> dict[str, object]:
        if type(repair_window_minutes) is not int or repair_window_minutes not in (5, 10):
            raise BusinessError("INVALID_TERMS", "repair_window_minutes must be 5 or 10")
        job = self._job(job_id)
        if job["status"] not in ("PROPOSED", "COUNTERED"):
            raise BusinessError("INVALID_STATE", "accepted agreement terms cannot be changed")
        previous = self._agreement(job)
        terms = json.loads(previous["terms_json"])
        terms["repair_window_minutes"] = repair_window_minutes
        version = job["current_version"] + 1
        self.connection.execute(
            """INSERT INTO agreement_versions
               (job_id, version, terms_json, source_csv, source_hash, checker_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, version, json.dumps(terms), previous["source_csv"], previous["source_hash"],
             previous["checker_version"], timestamp(now)),
        )
        self.connection.execute(
            "UPDATE jobs SET current_version = ?, status = 'COUNTERED', updated_at = ? WHERE job_id = ?",
            (version, timestamp(now), job_id),
        )
        return {"job_id": job_id, "version": version, "status": "COUNTERED"}

    def _accept_agreement(self, now: datetime, job_id: str, version: int) -> dict[str, object]:
        if type(version) is not int or version <= 0:
            raise BusinessError("INVALID_TERMS", "version must be a positive integer")
        job = self._job(job_id)
        if version != job["current_version"]:
            raise BusinessError("VERSION_MISMATCH", "accept the current agreement version")
        if job["status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED"):
            raise BusinessError("INVALID_STATE", "agreement acceptance is closed")
        self.connection.execute(
            """INSERT INTO acceptances (job_id, version, identity, accepted_at) VALUES (?, ?, ?, ?)
               ON CONFLICT (job_id, version, identity) DO NOTHING""",
            (job_id, version, self.identity, timestamp(now)),
        )
        accepted_by = self._accepted_by(job)
        status = job["status"]
        if accepted_by == ["buyer", "provider"] and status != "ACCEPTED":
            status = "ACCEPTED"
            self.connection.execute(
                "UPDATE jobs SET status = 'ACCEPTED', accepted_at = ?, updated_at = ? WHERE job_id = ?",
                (timestamp(now), timestamp(now), job_id),
            )
        return {"job_id": job_id, "version": version, "accepted_by": accepted_by, "status": status}

    def _fund_job(self, now: datetime, job_id: str) -> dict[str, object]:
        job = self._job(job_id)
        if job["status"] == "CANCELLED" and job["cancellation_reason"] == FIRST_SUBMISSION_EXPIRED:
            raise BusinessError("DEADLINE_PASSED", "first-submission deadline has passed")
        if job["status"] not in ("ACCEPTED", "FUNDED"):
            raise BusinessError("INVALID_STATE", "funding requires an accepted agreement")
        if self._accepted_by(job) != ["buyer", "provider"]:
            raise BusinessError("INVALID_STATE", "both parties must accept the current version")
        self._write_settlement(job_id, "SIMULATED_FUNDING", now)
        if job["status"] == "ACCEPTED":
            self.connection.execute(
                """UPDATE jobs SET status = 'FUNDED', funded_at = ?, updated_at = ?,
                   first_submission_deadline = ? WHERE job_id = ?""",
                (timestamp(now), timestamp(now), timestamp(now + self.first_submit_window), job_id),
            )
        return {"job_id": job_id, "status": "FUNDED", "simulated": True}

    def _submit_delivery(self, now: datetime, job_id: str, delivery: object) -> dict[str, object]:
        job = self._job(job_id)
        if job["status"] == "CANCELLED" and job["cancellation_reason"] in (
            FIRST_SUBMISSION_EXPIRED, REPAIR_EXPIRED, CHECK_ERROR_EXPIRED, DISPUTED_FAIL,
        ):
            raise BusinessError("DEADLINE_PASSED", "submission deadline has passed")
        if job["status"] not in ("FUNDED", "FAILED", "CHECK_ERROR"):
            raise BusinessError("INVALID_STATE", "submission requires funding or an eligible retry")
        if self._accepted_by(job) != ["buyer", "provider"] or not self._has_event(job_id, "SIMULATED_FUNDING"):
            raise BusinessError("INVALID_STATE", "submission requires mutual acceptance and simulated funding")
        agreement = self._agreement(job)
        used, _ = self._repair_history(job, agreement)
        if used >= json.loads(agreement["terms_json"])["max_repairs"]:
            raise BusinessError("REPAIR_LIMIT_REACHED", "the agreed repair has already been used")
        response_deadline = job[{
            "FUNDED": "first_submission_deadline", "FAILED": "repair_deadline", "CHECK_ERROR": "recovery_deadline",
        }[job["status"]]]
        version = job["current_submission_version"] + 1
        self.connection.execute(
            """INSERT INTO submissions (job_id, submission_version, agreement_version, delivery_json,
               submitted_by, submitted_at, response_deadline) VALUES (?, ?, ?, ?, 'provider', ?, ?)""",
            (job_id, version, job["current_version"], json.dumps(delivery), timestamp(now), response_deadline),
        )
        self.connection.execute(
            "UPDATE jobs SET status = 'SUBMITTED', current_submission_version = ?, updated_at = ? WHERE job_id = ?",
            (version, timestamp(now), job_id),
        )
        source_hash = hashlib.sha256(agreement["source_csv"].encode("utf-8")).hexdigest()
        checker_version = checker.CHECKER_VERSION
        try:
            outcome = checker.check_delivery(agreement["source_csv"], delivery)
        except Exception as exc:
            logger.error("Checker failed job_id=%s submission_version=%s exception_type=%s",
                         job_id, version, type(exc).__name__)
            outcome = {"source_hash": source_hash, "checker_version": checker_version,
                       "verdict": "UNKNOWN", "errors": []}
        checked_at = self.clock()
        self.connection.execute(
            """INSERT INTO check_results (job_id, submission_version, source_hash, checker_version,
               verdict, errors_json, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job_id, version, outcome["source_hash"], outcome["checker_version"], outcome["verdict"],
             json.dumps(outcome["errors"]), timestamp(checked_at)),
        )
        status = {"PASS": "IN_REVIEW", "FAIL": "FAILED", "UNKNOWN": "CHECK_ERROR"}[outcome["verdict"]]
        if not self._valid_result(job, agreement, self._result(job_id, version)):
            status = "CHECK_ERROR"
        review = timestamp(checked_at + self.review_window) if status == "IN_REVIEW" else None
        _, repair = self._repair_history(job, agreement)
        recovery = response_deadline if status == "CHECK_ERROR" else None
        self.connection.execute(
            """UPDATE jobs SET status = ?, review_deadline = ?, repair_deadline = ?, recovery_deadline = ?,
               updated_at = ? WHERE job_id = ?""",
            (status, review, repair, recovery, timestamp(checked_at), job_id),
        )
        return {"job_id": job_id, "submission_version": version, "verdict": outcome["verdict"], "release_allowed": False}

    def _challenge_result(self, now: datetime, admission: sqlite3.Row | None,
                          job_id: str, submission_version: int, reason_code: str) -> dict[str, object]:
        job = self._job(job_id)
        if type(submission_version) is not int or submission_version <= 0:
            raise BusinessError("INVALID_TERMS", "submission_version must be a positive integer")
        if reason_code not in ("SOURCE_MISMATCH", "CHECKER_VERSION_MISMATCH", "DISPUTE_FAIL"):
            raise BusinessError("INVALID_TERMS", "unsupported challenge reason_code")
        result = self._result(job_id, submission_version)
        if result is None:
            raise BusinessError("NOT_FOUND", "submission result not found")
        if submission_version != job["current_submission_version"] or result["agreement_version"] != job["current_version"]:
            raise BusinessError("VERSION_MISMATCH", "challenge must address the current submission and agreement")
        if admission is None or admission["status"] not in ("IN_REVIEW", "FAILED"):
            if job["status"] == "CANCELLED" and job["cancellation_reason"] in (
                FIRST_SUBMISSION_EXPIRED, REPAIR_EXPIRED, CHECK_ERROR_EXPIRED, DISPUTED_FAIL,
            ):
                raise BusinessError("DEADLINE_PASSED", "challenge deadline has passed")
            raise BusinessError("INVALID_STATE", "challenge requires a result in review or failed")
        cutoff = admission["review_deadline" if admission["status"] == "IN_REVIEW" else "repair_deadline"]
        if now >= datetime.fromisoformat(cutoff):
            raise BusinessError("DEADLINE_PASSED", "challenge deadline has passed")
        if self._accepted_by(job) != ["buyer", "provider"]:
            raise BusinessError("INVALID_STATE", "challenge requires the mutually accepted agreement")

        evidence = {"agreement_version": result["agreement_version"]}
        if reason_code == "DISPUTE_FAIL":
            if job["status"] != "FAILED" or result["verdict"] != "FAIL":
                raise BusinessError("INVALID_STATE", "DISPUTE_FAIL requires a current failed result")
            outcome, reason = "RECORDED", "failure dispute recorded; verdict unchanged"
            evidence["verdict"] = result["verdict"]
        else:
            field, label = {
                "SOURCE_MISMATCH": ("source_hash", "source hash"),
                "CHECKER_VERSION_MISMATCH": ("checker_version", "checker version"),
            }[reason_code]
            expected, actual = self._agreement(job)[field], result[field]
            outcome = "REJECTED" if expected == actual else "ACCEPTED"
            reason = f"{label} {'matches' if expected == actual else 'differs from'} agreement"
            evidence.update(expected=expected, actual=actual)

        challenge_id = f"ch-{uuid4().hex}"
        self.connection.execute(
            """INSERT INTO challenges (challenge_id, job_id, submission_version, identity, reason_code,
               outcome, reason, evidence_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (challenge_id, job_id, submission_version, self.identity, reason_code,
             outcome, reason, json.dumps(evidence), timestamp(now)),
        )
        # Advancement already applied bounded recovery for a mismatched result.
        return {"challenge_id": challenge_id, "outcome": outcome, "reason": reason}

    def _get_result(self, now: datetime, job_id: str, submission_version: int) -> dict[str, object]:
        job = self._job(job_id)
        if type(submission_version) is not int or submission_version <= 0:
            raise BusinessError("INVALID_TERMS", "submission_version must be a positive integer")
        result = self._result(job_id, submission_version)
        if result is None:
            raise BusinessError("NOT_FOUND", "submission result not found")
        settlement = ("RELEASED" if self._has_event(job_id, "SIMULATED_RELEASE") else
                      "REFUNDED" if self._has_event(job_id, "SIMULATED_REFUND") else "NONE")
        return {
            "job_id": job_id, "agreement_version": result["agreement_version"],
            "submission_version": submission_version, "checker_version": result["checker_version"],
            "verdict": result["verdict"], "errors": json.loads(result["errors_json"]),
            "release_allowed": self._release_allowed(job, submission_version, now),
            "settlement": {"status": settlement, "simulated": True},
            "receipt": self._receipt(job) if job["status"] in ("RELEASED", "CANCELLED") else None,
        }

    def _receipt(self, job: sqlite3.Row) -> dict[str, object]:
        def rows(query):
            return [dict(row) for row in self.connection.execute(query, (job["job_id"],))]

        agreements = rows("SELECT version, terms_json, source_hash, checker_version, created_at FROM agreement_versions WHERE job_id = ? ORDER BY version")
        for agreement in agreements:
            terms = json.loads(agreement.pop("terms_json"))
            agreement.update({key: terms[key] for key in ("template_id", "repair_window_minutes", "max_repairs")})
        reports = rows("""SELECT r.submission_version, s.agreement_version, r.source_hash, r.checker_version,
            r.verdict, r.errors_json, r.checked_at FROM check_results r JOIN submissions s
            USING (job_id, submission_version) WHERE r.job_id = ? ORDER BY r.submission_version""")
        for report in reports:
            report["errors"] = json.loads(report.pop("errors_json"))
        events = rows("SELECT event_type, simulated, created_at FROM settlement_events WHERE job_id = ? ORDER BY created_at, event_type")
        for event in events:
            event["simulated"] = bool(event["simulated"])
        challenges = rows("""SELECT challenge_id, submission_version, identity, reason_code, outcome,
            reason, evidence_json, created_at FROM challenges WHERE job_id = ? ORDER BY created_at, challenge_id""")
        for challenge in challenges:
            challenge["evidence"] = json.loads(challenge.pop("evidence_json"))
        return {
            "job_id": job["job_id"], "status": job["status"],
            "cancellation_reason": job["cancellation_reason"],
            "provider_fault": None if job["provider_fault"] is None else bool(job["provider_fault"]),
            "agreement_versions": agreements,
            "acceptances": rows("SELECT version, identity, accepted_at FROM acceptances WHERE job_id = ? ORDER BY version, identity"),
            "submissions": rows("""SELECT submission_version, agreement_version, submitted_by, submitted_at,
                response_deadline FROM submissions WHERE job_id = ? ORDER BY submission_version"""),
            "check_results": reports,
            "challenges": challenges,
            "settlement_events": events,
        }

    def _retrieve_delivery(self, now: datetime, job_id: str) -> dict[str, object]:
        job = self._job(job_id)
        if not self._release_allowed(job, job["current_submission_version"], now):
            raise BusinessError("PERMISSION_DENIED", "delivery available only after RELEASED")
        submission = self.connection.execute(
            "SELECT delivery_json FROM submissions WHERE job_id = ? AND submission_version = ?",
            (job_id, job["current_submission_version"]),
        ).fetchone()
        return {"job_id": job_id, "delivery": json.loads(submission["delivery_json"])}
