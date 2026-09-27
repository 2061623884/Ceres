"""Request-level idempotency: one reservation/receipt per HTTP turn request.

A Guide turn is one HTTP request. This service coordinates exactly that one
request identity ``(owner_id, session_id, request_id)`` plus its body digest:

* ``lookup_completed``/``reserve`` authenticate the session and validate the
  digest. A **completed** request returns its stored response (replay executes
  nothing and writes nothing); a **recorded failure** raises the original error
  again (same code/message/retryable, same HTTP status); a request still
  **in progress** is ``TURN_IN_PROGRESS``; a different body under the same
  ``request_id`` is always ``IDEMPOTENCY_CONFLICT``.
* A row whose worker died without recording a result is reported as an explicit
  unknown-outcome error. It is **never** reclaimed, taken over or re-executed.
* ``assert_owned``/``complete`` fence the single transaction: a stale worker
  whose lease was taken cannot overwrite the outcome. ``complete`` flushes only,
  so business effects and the receipt land in the caller's one commit boundary.

There is no cross-request resume, alias, logical-run or step-sequence binding.
The legacy ``logical_run_id``/``step_kind``/``step_seq``/``commit_key``/
``aliased_record_id`` columns may still exist on old rows; nothing here reads or
writes them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cart import TurnRequestRecord
from app.models.session import GuideSession

DEFAULT_LEASE_TTL = timedelta(seconds=120)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_RETRYABLE_FAILED = "retryable_failed"
STATUS_FAILED = "failed"

ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RUNNING)
FAILED_STATUSES = (STATUS_FAILED, STATUS_RETRYABLE_FAILED)

#: Matches SQLAlchemy's SQLite DATETIME storage format, so raw comparisons in
#: ``text()`` statements line up with ORM-written values.
_DT_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def _dt_param(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime(_DT_FORMAT)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    """Normalize a value read through ``text()`` (raw string on SQLite)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    return _as_utc(datetime.fromisoformat(str(value)))


# The columns this service actually uses; legacy run/step/alias/commit-key
# columns are deliberately neither read nor written.
_ROW_COLUMNS = (
    "id, owner_id, session_id, expected_task_id, request_id, request_digest, "
    "status, response_json, lease_token, lease_expires_at, created_at"
)


@dataclass(frozen=True)
class Reservation:
    """A held request reservation, or an already-completed receipt.

    ``completed_receipt`` set means the request was already committed: publish it
    and execute nothing. Otherwise ``token`` is the fencing token required by
    ``complete``.
    """

    record_id: int
    session_id: str
    request_id: str
    token: str | None = None
    completed_receipt: dict[str, Any] | None = None
    lease_expires_at: datetime | None = None

    @property
    def is_completed(self) -> bool:
        return self.completed_receipt is not None


@dataclass(frozen=True)
class _RecordView:
    id: int
    owner_id: str
    session_id: str
    request_id: str
    request_digest: str
    status: str
    response_json: str | None
    lease_token: str | None
    lease_expires_at: datetime | None
    created_at: datetime | None


class TurnReceiptService:
    """Request-level reservation/receipt coordination for one owner.

    Usage::

        svc = TurnReceiptService(session_factory, owner_id)
        receipt = svc.lookup_completed(sid, request_id, digest)
        if receipt is not None:
            return receipt
        reservation = svc.reserve(sid, request_id, digest)
        if reservation.is_completed:
            return reservation.completed_receipt
        try:
            ...business effects on the caller's session...
            svc.complete(db, reservation, response)
            db.commit()           # caller owns the single commit boundary
        except Exception:
            db.rollback()
            svc.fail(sid, request_id, token=reservation.token, error=...)
            raise
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        owner_id: str,
        *,
        lease_ttl: timedelta = DEFAULT_LEASE_TTL,
        clock: Callable[[], datetime] | None = None,
    ):
        self._session_factory = session_factory
        self.owner_id = owner_id
        self.lease_ttl = lease_ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------ reads

    def lookup_completed(
        self,
        session_id: str,
        request_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
        """Return the fixed response for this request, or ``None`` when unknown.

        Raises ``IDEMPOTENCY_CONFLICT`` for a reused id with a different body,
        ``TURN_IN_PROGRESS`` for a live request, the recorded original error for
        a finished failure, and an explicit unknown-outcome error for a request
        whose worker never recorded a result.
        """
        db = self._session_factory()
        try:
            self._authorize(db, session_id)
            view = self._find_by_http(db, session_id, request_id)
            if view is None:
                return None
            self._check_binding(view, request_digest)
            return self._resolve(view).completed_receipt
        finally:
            db.close()

    # ----------------------------------------------------------- reservation

    def reserve(
        self,
        session_id: str,
        request_id: str,
        request_digest: str,
        *,
        expected_task_id: str | None = None,
    ) -> Reservation:
        """Reserve this HTTP request's single step.

        Returns a :class:`Reservation` holding a fencing ``token``, or one whose
        ``completed_receipt`` is set when the request was already committed. A
        finished failure replays its original error instead of re-executing.
        """
        db = self._session_factory()
        try:
            self._authorize(db, session_id)
            view = self._find_by_http(db, session_id, request_id)
            if view is not None:
                self._check_binding(view, request_digest)
                return self._resolve(view)
            return self._insert_pending(
                db,
                session_id=session_id,
                request_id=request_id,
                request_digest=request_digest,
                expected_task_id=expected_task_id,
            )
        finally:
            db.close()

    def _resolve(self, view: _RecordView) -> Reservation:
        """The row's real outcome: a completed receipt, a stored error or a refusal.

        A finished request is never silently re-executed: a completed row replays
        its response, a failed row replays its original error, a live row is
        in-progress, and a stale row is an explicit unknown outcome.
        """
        if view.status == STATUS_COMPLETED and view.response_json:
            return self._completed_reservation(view)
        if view.status in FAILED_STATUSES:
            self._raise_recorded_failure(view)
        if view.status in ACTIVE_STATUSES:
            if not self._is_expired(view):
                raise AppError(
                    409,
                    "TURN_IN_PROGRESS",
                    "Turn already in progress",
                    retryable=True,
                )
            raise AppError(
                409,
                "TURN_STALLED",
                "上一轮未记录结果，无法确认是否已写入；请用新的 request_id 重试。",
                retryable=False,
            )
        raise AppError(
            409,
            "TURN_NOT_RESOLVED",
            f"Request is in an unresolvable state: {view.status}",
            retryable=False,
        )

    # ------------------------------------------------------------- receipts

    def assert_owned(self, db: Session, reservation: Reservation) -> TurnRequestRecord:
        """Verify this token still owns the reservation, else raise.

        Called by the caller immediately before its final business write, as a
        raw SELECT so it always reads the committed row. The authoritative fence
        is the conditional UPDATE in :meth:`complete`. This method never commits
        or writes.
        """
        if reservation.token is None:
            raise AppError(
                409,
                "RESERVATION_NOT_ACTIVE",
                "Reservation has no active lease",
                retryable=True,
            )
        row = self._fetch_row(db, reservation.session_id, reservation.record_id)
        if row is None:
            raise AppError(409, "RESERVATION_LOST", "Reservation no longer exists")
        if row["status"] not in ACTIVE_STATUSES:
            raise AppError(409, "RESERVATION_LOST", "Reservation is no longer active")
        if row["lease_token"] != reservation.token:
            raise AppError(
                409, "TURN_LEASE_LOST", "Reservation was taken over by another attempt"
            )
        expires = _parse_dt(row["lease_expires_at"])
        if expires is not None and self._now() >= expires:
            raise AppError(
                409, "TURN_LEASE_EXPIRED", "Reservation lease has expired", retryable=True
            )
        return self._row_to_record(row)

    def complete(
        self,
        db: Session,
        reservation: Reservation,
        response: dict[str, Any],
    ) -> TurnRequestRecord:
        """Write the receipt marker + fixed response into the caller's session.

        The final write is a conditional UPDATE (CAS) on the committed row:
        ``owner_id``/``session_id``/``request_id``/``status IN (pending,running)``
        and ``lease_token = token`` with an unexpired lease. Zero rows raises, so
        a stale worker cannot overwrite a new attempt. Flushes only; the caller's
        single commit boundary persists the receipt with the business effects.
        """
        self.assert_owned(db, reservation)
        payload = json.dumps(response)
        result = db.execute(
            text(
                "UPDATE turn_request_records "
                "SET status = 'completed', response_json = :payload, "
                "lease_token = NULL, lease_expires_at = NULL "
                "WHERE id = :record_id AND owner_id = :owner_id "
                "AND session_id = :session_id AND request_id = :request_id "
                "AND status IN ('pending', 'running') "
                "AND lease_token = :token "
                "AND (lease_expires_at IS NULL OR lease_expires_at > :now)"
            ),
            {
                "payload": payload,
                "record_id": reservation.record_id,
                "owner_id": self.owner_id,
                "session_id": reservation.session_id,
                "request_id": reservation.request_id,
                "token": reservation.token,
                "now": _dt_param(self._now()),
            },
        )
        if result.rowcount != 1:
            raise AppError(
                409,
                "TURN_LEASE_LOST",
                "Reservation lease was taken over before it could commit",
                retryable=True,
            )
        db.flush()
        row = self._fetch_row(db, reservation.session_id, reservation.record_id)
        if row is None:
            raise AppError(409, "RESERVATION_LOST", "Reservation no longer exists")
        return self._row_to_record(row)

    def fail(
        self,
        session_id: str,
        request_id: str,
        *,
        token: str | None = None,
        error: dict[str, Any] | None = None,
        retryable: bool = False,
        code: str = "TURN_FAILED",
        message: str = "Turn failed",
    ) -> bool:
        """Record the real failure of a live reservation in its own transaction.

        ``error`` is the original business error (``code``/``message``/
        ``retryable`` and, optionally, ``http_status``): a later request with the
        same ``request_id`` replays exactly this error and never re-executes.
        Returns ``True`` when a live reservation was recorded. A completed
        receipt is never touched.
        """
        recorded = dict(error) if error else {
            "code": code,
            "message": message,
            "retryable": retryable,
        }
        status = (
            STATUS_RETRYABLE_FAILED if recorded.get("retryable") else STATUS_FAILED
        )
        data: dict[str, Any] = {"error": recorded}
        http_status = recorded.get("http_status")
        if isinstance(http_status, int):
            data["http_status"] = http_status
        payload = json.dumps(data)
        token_clause = "AND lease_token IS NULL" if token is None else "AND lease_token = :token"
        db = self._session_factory()
        try:
            result = db.execute(
                text(
                    "UPDATE turn_request_records "
                    "SET status = :status, response_json = :payload, lease_token = NULL, "
                    "lease_expires_at = NULL "
                    "WHERE owner_id = :owner_id AND session_id = :session_id "
                    "AND request_id = :request_id "
                    "AND status IN ('pending', 'running') "
                    + token_clause
                ),
                {
                    "status": status,
                    "payload": payload,
                    "owner_id": self.owner_id,
                    "session_id": session_id,
                    "request_id": request_id,
                    **({"token": token} if token is not None else {}),
                },
            )
            db.commit()
            return result.rowcount == 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ------------------------------------------------------------- internals

    def _now(self) -> datetime:
        return _as_utc(self._clock()) or datetime.now(timezone.utc)

    def _fetch_row(
        self, db: Session, session_id: str, record_id: int
    ) -> dict[str, Any] | None:
        """Read the committed reservation row directly, bypassing identity maps."""
        row = db.execute(
            text(
                f"SELECT {_ROW_COLUMNS} FROM turn_request_records "
                "WHERE id = :record_id AND owner_id = :owner_id "
                "AND session_id = :session_id"
            ),
            {
                "record_id": record_id,
                "owner_id": self.owner_id,
                "session_id": session_id,
            },
        ).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> TurnRequestRecord:
        """Detached snapshot; never attached to a session."""
        record = TurnRequestRecord()
        for key, value in row.items():
            if key in ("lease_expires_at", "created_at"):
                value = _parse_dt(value)
            setattr(record, key, value)
        return record

    def _authorize(self, db: Session, session_id: str) -> None:
        session = db.get(GuideSession, session_id)
        if session is None:
            raise AppError(404, "SESSION_NOT_FOUND", "Session not found")
        if session.owner_id != self.owner_id:
            raise AppError(403, "FORBIDDEN", "Session does not belong to this owner")

    def _find_by_http(
        self, db: Session, session_id: str, request_id: str
    ) -> _RecordView | None:
        record = (
            db.query(TurnRequestRecord)
            .filter_by(
                owner_id=self.owner_id,
                session_id=session_id,
                request_id=request_id,
            )
            .first()
        )
        return self._view(record)

    @staticmethod
    def _view(record: TurnRequestRecord | None) -> _RecordView | None:
        if record is None:
            return None
        return _RecordView(
            id=record.id,
            owner_id=record.owner_id,
            session_id=record.session_id,
            request_id=record.request_id,
            request_digest=record.request_digest,
            status=record.status,
            response_json=record.response_json,
            lease_token=record.lease_token,
            lease_expires_at=_as_utc(record.lease_expires_at),
            created_at=_as_utc(record.created_at),
        )

    def _is_expired(self, view: _RecordView) -> bool:
        now = self._now()
        if view.lease_expires_at is not None:
            return now >= view.lease_expires_at
        # Legacy / lease-less row: stale once it is older than one lease TTL.
        created = view.created_at or now
        return now - created >= self.lease_ttl

    def _check_binding(self, view: _RecordView, request_digest: str) -> None:
        if view.request_digest != request_digest:
            raise AppError(
                409, "IDEMPOTENCY_CONFLICT", "Request ID reused with different body"
            )

    def _raise_recorded_failure(self, view: _RecordView) -> None:
        """Re-raise the exact error this request was originally recorded with."""
        data = self._payload(view)
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        code = str(error.get("code") or "TURN_FAILED")
        message = str(error.get("message") or "Turn failed")
        retryable = bool(error.get("retryable"))
        status = data.get("http_status")
        if not isinstance(status, int) or not (400 <= status <= 599):
            status = 502 if retryable else 400
        raise AppError(status, code, message, retryable=retryable)

    def _payload(self, view: _RecordView) -> dict[str, Any]:
        if not view.response_json:
            return {}
        try:
            data = json.loads(view.response_json)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _insert_pending(
        self,
        db: Session,
        *,
        session_id: str,
        request_id: str,
        request_digest: str,
        expected_task_id: str | None,
    ) -> Reservation:
        token = uuid4().hex
        expires = self._now() + self.lease_ttl
        record = TurnRequestRecord(
            owner_id=self.owner_id,
            session_id=session_id,
            expected_task_id=expected_task_id,
            request_id=request_id,
            request_digest=request_digest,
            status=STATUS_PENDING,
            lease_token=token,
            lease_expires_at=expires,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            # Lost the race to another reservation for the same HTTP triple;
            # re-read and honour whatever the winner recorded.
            db.rollback()
            view = self._find_by_http(db, session_id, request_id)
            if view is None:
                raise AppError(
                    409, "TURN_IN_PROGRESS", "Turn already in progress", retryable=True
                ) from None
            self._check_binding(view, request_digest)
            return self._resolve(view)
        return Reservation(
            record_id=record.id,
            session_id=session_id,
            request_id=request_id,
            token=token,
            lease_expires_at=expires,
        )

    @staticmethod
    def _completed_reservation(view: _RecordView) -> Reservation:
        return Reservation(
            record_id=view.id,
            session_id=view.session_id,
            request_id=view.request_id,
            token=None,
            completed_receipt=json.loads(view.response_json or "null"),
        )


__all__ = [
    "ACTIVE_STATUSES",
    "DEFAULT_LEASE_TTL",
    "FAILED_STATUSES",
    "Reservation",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RETRYABLE_FAILED",
    "STATUS_RUNNING",
    "TurnReceiptService",
]
