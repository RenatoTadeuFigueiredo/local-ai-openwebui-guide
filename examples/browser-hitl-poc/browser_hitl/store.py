from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


AGENT_ACTIVE = "AGENT_ACTIVE"
WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
HUMAN_ACTIVE = "HUMAN_ACTIVE"
READY_TO_RESUME = "READY_TO_RESUME"
DONE = "DONE"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
TERMINAL_STATES = {DONE, FAILED, EXPIRED}


class StoreError(RuntimeError):
    pass


class NotFound(StoreError):
    pass


class Conflict(StoreError):
    pass


class Locked(StoreError):
    pass


class Forbidden(StoreError):
    pass


def now() -> int:
    return int(time.time())


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Store:
    def __init__(self, path: Path, audit_log: Path) -> None:
        self.path = path
        self.audit_log = audit_log
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            con = sqlite3.connect(self.path, timeout=15)
            try:
                con.execute("PRAGMA foreign_keys=ON")
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=FULL")
                con.executescript(
                    """
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    access_email TEXT,
                    runtime_slot INTEGER NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    epoch INTEGER NOT NULL,
                    chat_id TEXT,
                    current_url TEXT,
                    runtime_slot INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    last_heartbeat_at INTEGER NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES profiles(user_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_live_session_per_user
                ON sessions(user_id)
                WHERE state NOT IN ('DONE', 'FAILED', 'EXPIRED');

                CREATE TABLE IF NOT EXISTS grants (
                    grant_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    owner_email TEXT,
                    epoch INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    redeemed_at INTEGER,
                    active_expires_at INTEGER,
                    completed_at INTEGER,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS ix_grants_session ON grants(session_id);
                CREATE INDEX IF NOT EXISTS ix_grants_token_hash ON grants(token_hash);
                """
                )
                profile_columns = {
                    str(row[1]) for row in con.execute("PRAGMA table_info(profiles)")
                }
                if "access_email" not in profile_columns:
                    con.execute("ALTER TABLE profiles ADD COLUMN access_email TEXT")
                grant_columns = {
                    str(row[1]) for row in con.execute("PRAGMA table_info(grants)")
                }
                if "owner_email" not in grant_columns:
                    con.execute("ALTER TABLE grants ADD COLUMN owner_email TEXT")
                if "active_expires_at" not in grant_columns:
                    con.execute("ALTER TABLE grants ADD COLUMN active_expires_at INTEGER")
                con.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_profiles_access_email "
                    "ON profiles(access_email) WHERE access_email IS NOT NULL"
                )
                con.commit()
            finally:
                con.close()
        self.path.chmod(0o600)
        if self.audit_log.exists():
            self.audit_log.chmod(0o600)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            con = sqlite3.connect(self.path, timeout=15, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            try:
                con.execute("BEGIN IMMEDIATE")
                yield con
                con.execute("COMMIT")
            except Exception:
                try:
                    con.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                con.close()

    def audit(
        self,
        *,
        event: str,
        user_id: str | None,
        session_id: str | None,
        epoch: int | None,
        outcome: str = "ok",
        detail: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "ts": now(),
            "event": event,
            "user_id": user_id,
            "session_id": session_id,
            "epoch": epoch,
            "outcome": outcome,
        }
        if detail:
            payload["detail"] = detail[:200]
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
        with self._lock:
            with self.audit_log.open("a", encoding="utf-8") as handle:
                handle.write(line)
            self.audit_log.chmod(0o600)

    def provision_profile(
        self,
        user_id: str,
        display_name: str,
        access_email: str | None = None,
    ) -> dict[str, Any]:
        timestamp = now()
        normalized_email = access_email.strip().casefold() if access_email else None
        if normalized_email and (
            normalized_email.count("@") != 1
            or any(ord(character) < 33 or ord(character) == 127 for character in normalized_email)
        ):
            raise Conflict("Invalid Access email mapping")
        revoked_sessions: list[dict[str, Any]] = []
        identity_changed = False
        with self.transaction() as con:
            current = _row(con.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone())
            if current:
                # Identity changes remain explicit administrative operations. A
                # caller that omits access_email cannot erase a pinned mapping.
                pinned_email = normalized_email or current.get("access_email")
                identity_changed = pinned_email != current.get("access_email")
                try:
                    con.execute(
                        "UPDATE profiles SET display_name=?,access_email=?,enabled=1,updated_at=? WHERE user_id=?",
                        (display_name, pinned_email, timestamp, user_id),
                    )
                except sqlite3.IntegrityError as error:
                    raise Conflict("Access email is already assigned to another browser profile") from error
                if identity_changed:
                    revoked_sessions = [
                        dict(row)
                        for row in con.execute(
                            "SELECT * FROM sessions WHERE user_id=? AND state IN (?,?)",
                            (user_id, WAITING_FOR_HUMAN, HUMAN_ACTIVE),
                        )
                    ]
                    for session in revoked_sessions:
                        con.execute(
                            "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                            "WHERE session_id=? AND state IN (?,?)",
                            (
                                READY_TO_RESUME,
                                timestamp,
                                session["session_id"],
                                WAITING_FOR_HUMAN,
                                HUMAN_ACTIVE,
                            ),
                        )
                        con.execute(
                            "UPDATE grants SET status='REVOKED' WHERE session_id=? "
                            "AND status IN ('ISSUED','REDEEMED')",
                            (session["session_id"],),
                        )
            else:
                used_slots = {int(row[0]) for row in con.execute("SELECT runtime_slot FROM profiles")}
                runtime_slot = next((slot for slot in range(5) if slot not in used_slots), None)
                if runtime_slot is None:
                    raise Conflict("The local POC supports at most five provisioned browser profiles")
                try:
                    con.execute(
                        "INSERT INTO profiles(user_id,profile_id,display_name,access_email,runtime_slot,enabled,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (
                            user_id,
                            str(uuid.uuid4()),
                            display_name,
                            normalized_email,
                            runtime_slot,
                            1,
                            timestamp,
                            timestamp,
                        ),
                    )
                except sqlite3.IntegrityError as error:
                    raise Conflict("Access email is already assigned to another browser profile") from error
            profile = _row(con.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone())
        assert profile is not None
        self.audit(
            event="profile.identity_change" if identity_changed else "profile.provision",
            user_id=user_id,
            session_id=None,
            epoch=None,
        )
        for session in revoked_sessions:
            self.audit(
                event="profile.identity_change_revoke",
                user_id=user_id,
                session_id=str(session["session_id"]),
                epoch=int(session["epoch"]) + 1,
            )
        profile["_revoked_session_ids"] = [
            str(session["session_id"]) for session in revoked_sessions
        ]
        return profile

    def profile(self, user_id: str) -> dict[str, Any]:
        with self.transaction() as con:
            profile = _row(con.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone())
        if not profile or not profile["enabled"]:
            raise Forbidden("Browser profile is not provisioned for this user")
        return profile

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.transaction() as con:
            return [dict(item) for item in con.execute("SELECT * FROM profiles ORDER BY created_at")]

    def expire_issued_takeovers(self) -> int:
        """Fail closed when a one-time link expires before human redemption."""
        timestamp = now()
        expired: list[dict[str, Any]] = []
        with self.transaction() as con:
            rows = [
                dict(item)
                for item in con.execute(
                    "SELECT s.session_id,s.user_id,s.epoch,g.grant_id "
                    "FROM grants g JOIN sessions s ON s.session_id=g.session_id "
                    "WHERE g.status='ISSUED' AND g.expires_at<=? "
                    "AND s.state=? AND s.epoch=g.epoch",
                    (timestamp, WAITING_FOR_HUMAN),
                )
            ]
            for item in rows:
                session_cursor = con.execute(
                    "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                    "WHERE session_id=? AND state=? AND epoch=?",
                    (
                        READY_TO_RESUME,
                        timestamp,
                        item["session_id"],
                        WAITING_FOR_HUMAN,
                        item["epoch"],
                    ),
                )
                grant_cursor = con.execute(
                    "UPDATE grants SET status='EXPIRED' WHERE grant_id=? AND status='ISSUED'",
                    (item["grant_id"],),
                )
                if session_cursor.rowcount != 1 or grant_cursor.rowcount != 1:
                    raise Conflict("Expired takeover recovery lost a race")
                expired.append(item)
        for item in expired:
            self.audit(
                event="takeover.expire_unredeemed",
                user_id=item["user_id"],
                session_id=item["session_id"],
                epoch=int(item["epoch"]) + 1,
            )
        return len(expired)

    def create_or_resume_session(self, user_id: str, chat_id: str | None, url: str, runtime_slot: int) -> dict[str, Any]:
        self.expire_issued_takeovers()
        profile = self.profile(user_id)
        timestamp = now()
        with self.transaction() as con:
            existing = _row(
                con.execute(
                    "SELECT * FROM sessions WHERE user_id=? AND state NOT IN ('DONE','FAILED','EXPIRED') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            )
            if existing:
                if existing["state"] in {WAITING_FOR_HUMAN, HUMAN_ACTIVE}:
                    raise Locked("Human takeover is pending or active")
                # The URL is only the initial target for a new session. Resuming
                # must preserve the durable current page; navigation requires an
                # explicit fenced browser action after AGENT_ACTIVE is confirmed.
                con.execute(
                    "UPDATE sessions SET chat_id=COALESCE(?,chat_id), updated_at=?, "
                    "last_heartbeat_at=? WHERE session_id=?",
                    (chat_id, timestamp, timestamp, existing["session_id"]),
                )
                result = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (existing["session_id"],)).fetchone())
                event = "session.resume"
            else:
                session_id = str(uuid.uuid4())
                con.execute(
                    "INSERT INTO sessions(session_id,user_id,profile_id,state,epoch,chat_id,current_url,runtime_slot,"
                    "created_at,updated_at,last_heartbeat_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        session_id,
                        user_id,
                        profile["profile_id"],
                        AGENT_ACTIVE,
                        1,
                        chat_id,
                        url,
                        runtime_slot,
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                result = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
                event = "session.create"
        assert result is not None
        self.audit(event=event, user_id=user_id, session_id=result["session_id"], epoch=result["epoch"])
        return result

    def session(self, session_id: str, user_id: str | None = None) -> dict[str, Any]:
        with self.transaction() as con:
            if user_id:
                item = _row(
                    con.execute(
                        "SELECT * FROM sessions WHERE session_id=? AND user_id=?",
                        (session_id, user_id),
                    ).fetchone()
                )
            else:
                item = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
        if not item:
            raise NotFound("Browser session not found")
        return item

    def expire_active_takeovers(self) -> list[dict[str, Any]]:
        timestamp = now()
        expired: list[dict[str, Any]] = []
        with self.transaction() as con:
            rows = [
                dict(item)
                for item in con.execute(
                    "SELECT s.*,g.grant_id,g.active_expires_at "
                    "FROM sessions s JOIN grants g ON g.session_id=s.session_id "
                    "WHERE s.state=? AND g.status='REDEEMED' AND g.epoch=s.epoch "
                    "AND (g.active_expires_at IS NULL OR g.active_expires_at<=?)",
                    (HUMAN_ACTIVE, timestamp),
                )
            ]
            for item in rows:
                grant_cursor = con.execute(
                    "UPDATE grants SET status='EXPIRED' WHERE grant_id=? AND status='REDEEMED'",
                    (item["grant_id"],),
                )
                session_cursor = con.execute(
                    "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                    "WHERE session_id=? AND state=? AND epoch=?",
                    (
                        READY_TO_RESUME,
                        timestamp,
                        item["session_id"],
                        HUMAN_ACTIVE,
                        item["epoch"],
                    ),
                )
                if grant_cursor.rowcount != 1 or session_cursor.rowcount != 1:
                    raise Conflict("Expired active takeover recovery lost a race")
                expired.append(item)
        for item in expired:
            self.audit(
                event="takeover.expire_active",
                user_id=str(item["user_id"]),
                session_id=str(item["session_id"]),
                epoch=int(item["epoch"]) + 1,
            )
        return expired

    def active_session_for_user(self, user_id: str) -> dict[str, Any]:
        self.expire_issued_takeovers()
        self.expire_active_takeovers()
        with self.transaction() as con:
            item = _row(
                con.execute(
                    "SELECT * FROM sessions WHERE user_id=? AND state NOT IN ('DONE','FAILED','EXPIRED') "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            )
        if not item:
            raise NotFound("No active browser session")
        return item

    def assert_agent(self, session_id: str, user_id: str, epoch: int) -> dict[str, Any]:
        item = self.session(session_id, user_id)
        if item["state"] in {WAITING_FOR_HUMAN, HUMAN_ACTIVE}:
            self.audit(
                event="agent.blocked",
                user_id=user_id,
                session_id=session_id,
                epoch=item["epoch"],
                outcome="locked",
            )
            raise Locked("Human takeover is pending or active")
        if item["state"] != AGENT_ACTIVE:
            raise Conflict(f"Agent control is not active: {item['state']}")
        if int(item["epoch"]) != int(epoch):
            raise Conflict("Stale browser lease epoch")
        with self.transaction() as con:
            timestamp = now()
            con.execute(
                "UPDATE sessions SET last_heartbeat_at=?,updated_at=? WHERE session_id=?",
                (timestamp, timestamp, session_id),
            )
        return item

    def assert_human(self, session_id: str, epoch: int) -> dict[str, Any]:
        item = self.session(session_id)
        if item["state"] != HUMAN_ACTIVE or int(item["epoch"]) != int(epoch):
            raise Conflict("Human control is no longer active")
        return item

    def set_url(self, session_id: str, user_id: str, epoch: int, url: str) -> dict[str, Any]:
        self.assert_agent(session_id, user_id, epoch)
        with self.transaction() as con:
            cursor = con.execute(
                "UPDATE sessions SET current_url=?,updated_at=? WHERE session_id=? AND user_id=? AND epoch=? AND state=?",
                (url, now(), session_id, user_id, epoch, AGENT_ACTIVE),
            )
            if cursor.rowcount != 1:
                raise Locked("Browser control changed before dispatch")
        return self.session(session_id, user_id)

    def issue_takeover(
        self,
        session_id: str,
        user_id: str,
        epoch: int,
        ttl_seconds: int,
        *,
        user_email: str | None = None,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        timestamp = now()
        expires_at = timestamp + ttl_seconds
        with self.transaction() as con:
            session = _row(
                con.execute(
                    "SELECT * FROM sessions WHERE session_id=? AND user_id=?",
                    (session_id, user_id),
                ).fetchone()
            )
            if not session:
                raise NotFound("Browser session not found")
            profile = _row(
                con.execute("SELECT * FROM profiles WHERE user_id=? AND enabled=1", (user_id,)).fetchone()
            )
            owner_email = str((profile or {}).get("access_email") or "").strip().casefold()
            trusted_email = (user_email or owner_email).strip().casefold()
            if not owner_email or not hmac.compare_digest(owner_email, trusted_email):
                raise Forbidden("Open WebUI identity does not match the pinned Access identity")
            if session["state"] != AGENT_ACTIVE or int(session["epoch"]) != int(epoch):
                raise Conflict("Browser lease changed before takeover")
            next_epoch = int(session["epoch"]) + 1
            cursor = con.execute(
                "UPDATE sessions SET state=?,epoch=?,updated_at=? WHERE session_id=? AND user_id=? AND state=? AND epoch=?",
                (WAITING_FOR_HUMAN, next_epoch, timestamp, session_id, user_id, AGENT_ACTIVE, epoch),
            )
            if cursor.rowcount != 1:
                raise Conflict("Takeover transition lost a race")
            con.execute(
                "UPDATE grants SET status='REVOKED' WHERE session_id=? AND status IN ('ISSUED','REDEEMED')",
                (session_id,),
            )
            grant_id = str(uuid.uuid4())
            con.execute(
                "INSERT INTO grants(grant_id,token_hash,session_id,user_id,owner_email,epoch,status,created_at,expires_at) "
                "VALUES(?,?,?,?,?,?,'ISSUED',?,?)",
                (
                    grant_id,
                    token_hash(token),
                    session_id,
                    user_id,
                    owner_email,
                    next_epoch,
                    timestamp,
                    expires_at,
                ),
            )
            grant = _row(con.execute("SELECT * FROM grants WHERE grant_id=?", (grant_id,)).fetchone())
            updated = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
        assert grant is not None and updated is not None
        self.audit(event="takeover.issue", user_id=user_id, session_id=session_id, epoch=updated["epoch"])
        return token, grant, updated

    def grant_by_token(self, token: str) -> tuple[dict[str, Any], dict[str, Any]]:
        # The five-minute deadline applies only to redeeming an issued link.
        # Redemption rotates the issuance token, so this lookup intentionally
        # accepts only an ISSUED grant.
        self.expire_issued_takeovers()
        digest = token_hash(token)
        with self.transaction() as con:
            grant = _row(con.execute("SELECT * FROM grants WHERE token_hash=?", (digest,)).fetchone())
            if not grant or grant["status"] != "ISSUED":
                raise NotFound("Takeover link is invalid or expired")
            if int(grant["expires_at"]) < now():
                raise NotFound("Takeover link is invalid or expired")
            session = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (grant["session_id"],)).fetchone())
        if not session:
            raise NotFound("Browser session not found")
        return grant, session

    def redeem_takeover(
        self,
        token: str,
        active_expires_at: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        digest = token_hash(token)
        invalidated_digest = token_hash(secrets.token_urlsafe(48))
        timestamp = now()
        if active_expires_at <= timestamp:
            raise NotFound("Takeover link is invalid or expired")
        with self.transaction() as con:
            grant = _row(con.execute("SELECT * FROM grants WHERE token_hash=?", (digest,)).fetchone())
            if not grant or grant["status"] != "ISSUED" or int(grant["expires_at"]) < timestamp:
                raise NotFound("Takeover link is invalid or expired")
            session = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (grant["session_id"],)).fetchone())
            if not session or session["state"] != WAITING_FOR_HUMAN or int(session["epoch"]) != int(grant["epoch"]):
                raise Conflict("Browser session is no longer waiting for takeover")
            grant_cursor = con.execute(
                "UPDATE grants SET status='REDEEMED',redeemed_at=?,active_expires_at=?,token_hash=? "
                "WHERE grant_id=? AND status='ISSUED'",
                (
                    timestamp,
                    active_expires_at,
                    invalidated_digest,
                    grant["grant_id"],
                ),
            )
            if grant_cursor.rowcount != 1:
                raise Conflict("Takeover link was already used")
            session_cursor = con.execute(
                "UPDATE sessions SET state=?,updated_at=? WHERE session_id=? AND state=? AND epoch=?",
                (HUMAN_ACTIVE, timestamp, session["session_id"], WAITING_FOR_HUMAN, grant["epoch"]),
            )
            if session_cursor.rowcount != 1:
                raise Conflict("Takeover transition lost a race")
            updated_session = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session["session_id"],)).fetchone())
            updated_grant = _row(con.execute("SELECT * FROM grants WHERE grant_id=?", (grant["grant_id"],)).fetchone())
        assert updated_session is not None and updated_grant is not None
        self.audit(
            event="takeover.redeem",
            user_id=updated_session["user_id"],
            session_id=updated_session["session_id"],
            epoch=updated_session["epoch"],
        )
        return updated_grant, updated_session

    def active_grant(self, grant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        timestamp = now()
        expired: tuple[dict[str, Any], dict[str, Any]] | None = None
        with self.transaction() as con:
            grant = _row(
                con.execute(
                    "SELECT * FROM grants WHERE grant_id=? AND status='REDEEMED'",
                    (grant_id,),
                ).fetchone()
            )
            if not grant:
                raise NotFound("Active human takeover not found")
            session = _row(
                con.execute("SELECT * FROM sessions WHERE session_id=?", (grant["session_id"],)).fetchone()
            )
            if (
                not session
                or session["state"] != HUMAN_ACTIVE
                or int(session["epoch"]) != int(grant["epoch"])
            ):
                raise NotFound("Active human takeover not found")
            if not grant.get("active_expires_at") or int(grant["active_expires_at"]) <= timestamp:
                grant_cursor = con.execute(
                    "UPDATE grants SET status='EXPIRED' WHERE grant_id=? AND status='REDEEMED'",
                    (grant_id,),
                )
                session_cursor = con.execute(
                    "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                    "WHERE session_id=? AND state=? AND epoch=?",
                    (
                        READY_TO_RESUME,
                        timestamp,
                        session["session_id"],
                        HUMAN_ACTIVE,
                        grant["epoch"],
                    ),
                )
                if grant_cursor.rowcount != 1 or session_cursor.rowcount != 1:
                    raise Conflict("Expired human takeover recovery lost a race")
                expired = (grant, session)
        if expired:
            grant, session = expired
            self.audit(
                event="takeover.expire_active",
                user_id=str(session["user_id"]),
                session_id=str(session["session_id"]),
                epoch=int(session["epoch"]) + 1,
            )
            raise NotFound("Active human takeover expired")
        return grant, session

    def expire_active_grant(self, grant_id: str) -> dict[str, Any] | None:
        timestamp = now()
        with self.transaction() as con:
            grant = _row(
                con.execute(
                    "SELECT * FROM grants WHERE grant_id=? AND status='REDEEMED'",
                    (grant_id,),
                ).fetchone()
            )
            if not grant:
                return None
            session = _row(
                con.execute("SELECT * FROM sessions WHERE session_id=?", (grant["session_id"],)).fetchone()
            )
            if (
                not session
                or session["state"] != HUMAN_ACTIVE
                or int(session["epoch"]) != int(grant["epoch"])
            ):
                return None
            con.execute(
                "UPDATE grants SET status='EXPIRED' WHERE grant_id=? AND status='REDEEMED'",
                (grant_id,),
            )
            con.execute(
                "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                "WHERE session_id=? AND state=? AND epoch=?",
                (
                    READY_TO_RESUME,
                    timestamp,
                    session["session_id"],
                    HUMAN_ACTIVE,
                    grant["epoch"],
                ),
            )
        self.audit(
            event="takeover.expire_active",
            user_id=str(session["user_id"]),
            session_id=str(session["session_id"]),
            epoch=int(session["epoch"]) + 1,
        )
        return session

    def complete_takeover(self, grant_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        timestamp = now()
        with self.transaction() as con:
            grant = _row(
                con.execute(
                    "SELECT * FROM grants WHERE grant_id=? AND status='REDEEMED'",
                    (grant_id,),
                ).fetchone()
            )
            if not grant:
                raise NotFound("Active human takeover not found")
            session = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (grant["session_id"],)).fetchone())
            if not session or session["state"] != HUMAN_ACTIVE or int(session["epoch"]) != int(grant["epoch"]):
                raise Conflict("Human control is no longer active")
            next_epoch = int(session["epoch"]) + 1
            grant_cursor = con.execute(
                "UPDATE grants SET status='COMPLETED',completed_at=? WHERE grant_id=? AND status='REDEEMED'",
                (timestamp, grant["grant_id"]),
            )
            session_cursor = con.execute(
                "UPDATE sessions SET state=?,epoch=?,updated_at=? WHERE session_id=? AND state=? AND epoch=?",
                (READY_TO_RESUME, next_epoch, timestamp, session["session_id"], HUMAN_ACTIVE, grant["epoch"]),
            )
            if grant_cursor.rowcount != 1 or session_cursor.rowcount != 1:
                raise Conflict("Return-control transition lost a race")
            updated_session = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session["session_id"],)).fetchone())
            updated_grant = _row(con.execute("SELECT * FROM grants WHERE grant_id=?", (grant["grant_id"],)).fetchone())
        assert updated_session is not None and updated_grant is not None
        self.audit(
            event="takeover.complete",
            user_id=updated_session["user_id"],
            session_id=updated_session["session_id"],
            epoch=updated_session["epoch"],
        )
        return updated_grant, updated_session

    def assert_ready_to_resume(self, session_id: str, user_id: str) -> dict[str, Any]:
        session = self.session(session_id, user_id)
        if session["state"] != READY_TO_RESUME:
            if session["state"] == HUMAN_ACTIVE:
                raise Locked("Human control is active")
            raise Conflict(f"Session is not ready to resume: {session['state']}")
        return session

    def resume_agent(self, session_id: str, user_id: str) -> dict[str, Any]:
        timestamp = now()
        with self.transaction() as con:
            session = _row(con.execute("SELECT * FROM sessions WHERE session_id=? AND user_id=?", (session_id, user_id)).fetchone())
            if not session:
                raise NotFound("Browser session not found")
            if session["state"] != READY_TO_RESUME:
                if session["state"] == HUMAN_ACTIVE:
                    raise Locked("Human control is active")
                raise Conflict(f"Session is not ready to resume: {session['state']}")
            next_epoch = int(session["epoch"]) + 1
            cursor = con.execute(
                "UPDATE sessions SET state=?,epoch=?,updated_at=?,last_heartbeat_at=? WHERE session_id=? AND state=? AND epoch=?",
                (AGENT_ACTIVE, next_epoch, timestamp, timestamp, session_id, READY_TO_RESUME, session["epoch"]),
            )
            if cursor.rowcount != 1:
                raise Conflict("Resume transition lost a race")
            updated = _row(con.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())
        assert updated is not None
        self.audit(event="agent.resume", user_id=user_id, session_id=session_id, epoch=updated["epoch"])
        return updated

    def recover_fail_closed(self) -> int:
        timestamp = now()
        with self.transaction() as con:
            rows = [
                dict(item)
                for item in con.execute(
                    "SELECT * FROM sessions WHERE state IN ('WAITING_FOR_HUMAN','HUMAN_ACTIVE')"
                )
            ]
            for item in rows:
                con.execute(
                    "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? WHERE session_id=?",
                    (READY_TO_RESUME, timestamp, item["session_id"]),
                )
                con.execute(
                    "UPDATE grants SET status='REVOKED' WHERE session_id=? AND status IN ('ISSUED','REDEEMED')",
                    (item["session_id"],),
                )
        for item in rows:
            self.audit(
                event="startup.fail_closed",
                user_id=item["user_id"],
                session_id=item["session_id"],
                epoch=int(item["epoch"]) + 1,
            )
        return len(rows)

    def active_takeover_sessions(self) -> list[dict[str, Any]]:
        with self.transaction() as con:
            return [
                dict(item)
                for item in con.execute(
                    "SELECT * FROM sessions WHERE state IN (?,?)",
                    (WAITING_FOR_HUMAN, HUMAN_ACTIVE),
                )
            ]

    def abort_takeover(self, session_id: str) -> dict[str, Any] | None:
        timestamp = now()
        with self.transaction() as con:
            item = _row(
                con.execute(
                    "SELECT * FROM sessions WHERE session_id=? AND state IN (?,?)",
                    (session_id, WAITING_FOR_HUMAN, HUMAN_ACTIVE),
                ).fetchone()
            )
            if not item:
                return None
            con.execute(
                "UPDATE sessions SET state=?,epoch=epoch+1,updated_at=? "
                "WHERE session_id=? AND state IN (?,?)",
                (
                    READY_TO_RESUME,
                    timestamp,
                    session_id,
                    WAITING_FOR_HUMAN,
                    HUMAN_ACTIVE,
                ),
            )
            con.execute(
                "UPDATE grants SET status='REVOKED' WHERE session_id=? "
                "AND status IN ('ISSUED','REDEEMED')",
                (session_id,),
            )
        self.audit(
            event="operator.abort_takeover",
            user_id=str(item["user_id"]),
            session_id=session_id,
            epoch=int(item["epoch"]) + 1,
        )
        return item

    def abort_active_takeovers(self) -> list[dict[str, Any]]:
        """Operator-only local recovery for all pending or redeemed takeovers."""
        rows = self.active_takeover_sessions()
        aborted = [self.abort_takeover(str(item["session_id"])) for item in rows]
        return [item for item in aborted if item is not None]

    def abort_pending_takeovers(self) -> int:
        """Backward-compatible count for local operator recovery."""
        return len(self.abort_active_takeovers())
