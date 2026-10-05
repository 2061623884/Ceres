"""An explicit chat-opening lifecycle; role histories remain in their own stores."""
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from app.core.errors import AppError


@dataclass
class Handoff:
    handoff_id: str
    source_request_id: str
    target_role: str
    body: dict
    context: dict
    status: str = "pending"
    chunks: list[str] = field(default_factory=list)


@dataclass
class Opening:
    opening_id: str
    owner_id: str
    guide_session_id: str
    mercury_session_id: str
    role: str
    prompt_displayed: bool = False
    pending: Handoff | None = None
    pending_question: str | None = None
    recent_dialogue: list[dict] = field(default_factory=list)
    # Only V3 source requests / handoffs need this bounded-lifetime receipt.
    requests: dict[str, dict] = field(default_factory=dict)
    busy: bool = False
    closed: bool = False
    lock: Lock = field(default_factory=Lock)

    def view(self) -> dict:
        return {"opening_id": self.opening_id, "guide_session_id": self.guide_session_id,
                "mercury_session_id": self.mercury_session_id, "role": self.role,
                "prompt_displayed": self.prompt_displayed,
                "handoff_id": self.pending.handoff_id if self.pending else None}

    def require_open(self) -> None:
        if self.closed:
            raise AppError(404, "OPENING_NOT_FOUND", "没有找到本次聊天，请重新进入。")


class ChatOpenings:
    def __init__(self):
        self._openings: dict[str, Opening] = {}
        self._lock = Lock()

    def create(self, owner_id: str, guide_session_id: str, mercury_session_id: str,
               role: str) -> Opening:
        opening = Opening(f"open_{uuid4().hex}", owner_id, guide_session_id, mercury_session_id, role)
        with self._lock:
            self._openings[opening.opening_id] = opening
        return opening

    def require(self, opening_id: str, owner_id: str) -> Opening:
        with self._lock:
            opening = self._openings.get(opening_id)
        if opening is None or opening.owner_id != owner_id:
            raise AppError(404, "OPENING_NOT_FOUND", "没有找到本次聊天，请重新进入。")
        return opening

    def close(self, opening_id: str, owner_id: str) -> None:
        opening = self.require(opening_id, owner_id)
        with opening.lock:
            opening.require_open()
            if opening.busy:
                raise AppError(409, "TURN_IN_PROGRESS", "当前聊天仍在处理上一条消息，暂不能退出。")
            with self._lock:
                opening.closed = True
                del self._openings[opening_id]


chat_openings = ChatOpenings()
