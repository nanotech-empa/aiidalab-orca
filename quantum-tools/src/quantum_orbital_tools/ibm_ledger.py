"""Durable per-campaign QPU reservations and fail-closed submission recovery.

A submission is never retried after an uncertain outcome. Recovery binds a
positively identified provider job; an empty job search does not authorize
another submission. No credentials or raw provider errors are stored here.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


class LedgerError(RuntimeError):
    pass


class JobLedger:
    def __init__(self, directory=None):
        self.directory = Path(
            directory
            or os.environ.get(
                "QUANTUM_ORBITALS_LEDGER_DIR",
                Path.home() / ".local/share/quantum-orbital-tools/ibm",
            )
        )
        if self.directory.is_symlink():
            raise LedgerError("Ledger directory must not be a symlink")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.directory.stat()
        if info.st_uid != os.getuid():
            raise LedgerError("Ledger directory owner mismatch")
        self.directory.chmod(0o700)
        self.path = self.directory / "jobs.sqlite3"
        if self.path.is_symlink():
            raise LedgerError("Ledger file must not be a symlink")
        with self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY,budget REAL NOT NULL,created TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (pilot_id TEXT NOT NULL,mode TEXT NOT NULL,campaign_id TEXT NOT NULL,request_sha TEXT NOT NULL,state TEXT NOT NULL,reserved REAL NOT NULL,actual REAL,job_id TEXT,status TEXT,updated TEXT NOT NULL,PRIMARY KEY(pilot_id,mode))"
            )
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def prepare(self, plan, mode):
        if mode not in ["hardware", "server_mock"]:
            raise LedgerError("Unknown execution mode")
        pilot = plan["pilot_id"]
        campaign = plan["campaign_id"]
        budget = plan["budget_total_seconds"]
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM campaigns WHERE id=?", (campaign,)
            ).fetchone()
            if row and row["budget"] != budget:
                raise LedgerError("Campaign budget cannot change during a pilot")
            if not row:
                db.execute(
                    "INSERT INTO campaigns VALUES (?,?,?)", (campaign, budget, now())
                )
            old = db.execute(
                "SELECT * FROM jobs WHERE pilot_id=? AND mode=?", (pilot, mode)
            ).fetchone()
            if old:
                if (
                    old["request_sha"] != plan["request_sha256"]
                    or old["campaign_id"] != campaign
                ):
                    raise LedgerError("Pilot identity changed")
            else:
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,NULL,NULL,NULL,?)",
                    (
                        pilot,
                        mode,
                        campaign,
                        plan["request_sha256"],
                        "prepared",
                        0.0,
                        now(),
                    ),
                )
        return self.get(pilot, mode)

    def get(self, pilot, mode):
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE pilot_id=? AND mode=?", (pilot, mode)
            ).fetchone()
            if row is None:
                raise LedgerError("Unknown pilot")
            return dict(row)

    def claim_submission(self, plan, mode):
        """Atomically reserve the campaign budget and claim the single attempt."""
        self.prepare(plan, mode)
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE pilot_id=? AND mode=?",
                (plan["pilot_id"], mode),
            ).fetchone()
            if row["state"] != "prepared":
                return False
            reserve = (
                0.0
                if mode == "server_mock"
                else float(
                    plan["max_execution_seconds"] + plan["budget_margin_seconds"]
                )
            )
            used = db.execute(
                "SELECT COALESCE(SUM(CASE WHEN state IN ('terminal','budget_exceeded') AND actual IS NOT NULL THEN actual ELSE reserved END),0) FROM jobs WHERE campaign_id=? AND mode=?",
                (plan["campaign_id"], "hardware"),
            ).fetchone()[0]
            budget = db.execute(
                "SELECT budget FROM campaigns WHERE id=?", (plan["campaign_id"],)
            ).fetchone()[0]
            if used + reserve > budget + 1e-9:
                raise LedgerError("Campaign QPU budget is already used or reserved")
            db.execute(
                "UPDATE jobs SET state=?,reserved=?,updated=? WHERE pilot_id=? AND mode=?",
                ("submitting", reserve, now(), plan["pilot_id"], mode),
            )
        return True

    def ambiguous(self, pilot, mode):
        with self.transaction() as db:
            db.execute(
                "UPDATE jobs SET state=?,updated=? WHERE pilot_id=? AND mode=? AND job_id IS NULL",
                ("submission_unknown", now(), pilot, mode),
            )

    def bind(self, pilot, mode, job_id):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE pilot_id=? AND mode=?", (pilot, mode)
            ).fetchone()
            if row is None or row["state"] == "prepared":
                raise LedgerError("No submission attempt was claimed")
            if row["job_id"] and row["job_id"] != job_id:
                raise LedgerError("More than one provider job matched the pilot")
            db.execute(
                "UPDATE jobs SET job_id=?,state=?,updated=? WHERE pilot_id=? AND mode=?",
                (job_id, "submitted", now(), pilot, mode),
            )
        return self.get(pilot, mode)

    def observe(self, pilot, mode, status, actual_seconds=None):
        if actual_seconds is not None and (
            type(actual_seconds) not in [float, int]
            or not 0 <= actual_seconds < float("inf")
        ):
            raise LedgerError("Invalid measured QPU usage")
        terminal = status in ["DONE", "ERROR", "CANCELLED"]
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE pilot_id=? AND mode=?", (pilot, mode)
            ).fetchone()
            if row is None or not row["job_id"]:
                raise LedgerError("Cannot settle an unidentified job")
            if mode == "server_mock":
                actual_seconds = 0.0
            actual = (
                row["actual"]
                if actual_seconds is None
                else max(float(actual_seconds), row["actual"] or 0.0)
            )
            # Terminal status alone never releases a reservation: usage must be known.
            state = "terminal" if terminal else "submitted"
            if terminal and actual_seconds is None:
                state = "terminal_usage_unknown"
            budget = db.execute(
                "SELECT budget FROM campaigns WHERE id=?", (row["campaign_id"],)
            ).fetchone()[0]
            if actual is not None and actual > budget:
                state = "budget_exceeded"
            db.execute(
                "UPDATE jobs SET state=?,status=?,actual=?,updated=? WHERE pilot_id=? AND mode=?",
                (state, status, actual, now(), pilot, mode),
            )
        return self.get(pilot, mode)
