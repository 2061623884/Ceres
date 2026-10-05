"""Memory persistence and bounded recall; caller owns the transaction."""

import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agent.protocol import MemoryAction
from app.core.errors import AppError
from app.models.memory import ShoppingMemory


class MemoryService:
    def __init__(self, db: Session, owner_id: str):
        self.db = db
        self.owner_id = owner_id

    def list_valid(self) -> list[ShoppingMemory]:
        return list(self.db.scalars(select(ShoppingMemory).where(
            ShoppingMemory.owner_id == self.owner_id,
            or_(ShoppingMemory.expires_at.is_(None), ShoppingMemory.expires_at > datetime.now(timezone.utc)),
        ).order_by(ShoppingMemory.source.desc(), ShoppingMemory.updated_at.desc(), ShoppingMemory.memory_id)))

    def recall(self, message: str) -> list[dict]:
        # Stable preferences and feedback apply across shopping requests. Other
        # memories require lexical relevance, not a copied task or plan state.
        terms = {text or pair for text, pair in re.findall(r"([a-z0-9]+)|(?=([\u4e00-\u9fff]{2}))", message.casefold())}
        result = []
        remaining = 2000
        for row in self.list_valid():
            if row.category not in ("user", "feedback") and not any(term in row.content.casefold() for term in terms):
                continue
            if len(row.content) > remaining:
                continue
            result.append(row.to_dict())
            remaining -= len(row.content)
            if len(result) == 5:
                break
        return result

    def execute(self, action: MemoryAction) -> tuple[dict, str]:
        if action.verb == "list":
            records = [row.to_dict() for row in self.list_valid()]
            message = "已保存的有效记忆：\n" + "\n".join(
                f"{i}. [{row['category']}/{row['source']}] {row['content']}（{row['ref']}）"
                for i, row in enumerate(records, 1)
            ) if records else "当前没有保存的有效记忆。"
            return {"type": "memory", "status": "completed", "saved": False,
                    "reply_ok": True, "records": records}, message
        if action.verb == "save":
            row = ShoppingMemory(memory_id="memory-" + uuid4().hex, owner_id=self.owner_id,
                                 category=action.category, source="explicit", content=action.content)
            self.db.add(row)
        else:
            row = self.db.get(ShoppingMemory, action.ref)
            if row is None or row.owner_id != self.owner_id:
                raise AppError(404, "MEMORY_NOT_FOUND", "没有找到可管理的记忆。")
            if action.verb == "delete":
                self.db.delete(row)
                self.db.flush()
                return {"type": "memory", "status": "committed", "saved": True,
                        "reply_ok": True, "records": [row.to_dict()]}, f"已删除记忆：{row.content}"
            row.content = action.content
            if action.category is not None:
                row.category = action.category
            row.source = "explicit"
            row.expires_at = None
            row.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return {"type": "memory", "status": "committed", "saved": True,
                "reply_ok": True, "records": [row.to_dict()]}, f"已{'保存' if action.verb == 'save' else '更正'}记忆：{row.content}"
