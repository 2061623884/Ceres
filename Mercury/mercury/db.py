"""SQLite 连接与建表。"""

import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from mercury import config

_DATABASE_PATH: ContextVar[Path | None] = ContextVar("mercury_database_path", default=None)


@contextmanager
def use_database(path: str | None):
    """Bind the integrated Ceres database for one tool-calling turn."""
    token = _DATABASE_PATH.set(Path(path) if path is not None else None)
    try:
        yield
    finally:
        _DATABASE_PATH.reset(token)

SCHEMA = """
CREATE TABLE users (
  user_id TEXT PRIMARY KEY,
  name TEXT NOT NULL
);
CREATE TABLE orders (
  order_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  status TEXT NOT NULL,             -- paid / shipped / delivered / cancelled
  total_fen INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  delivered_at TEXT                 -- 签收时间，未签收为 NULL
);
CREATE TABLE order_items (
  item_id INTEGER PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES orders(order_id),
  product_name TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price_fen INTEGER NOT NULL,
  returnable INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE deliveries (
  order_id TEXT PRIMARY KEY REFERENCES orders(order_id),
  status TEXT NOT NULL,             -- shipping / delivered
  latest_description TEXT NOT NULL,
  eta TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE refunds (
  refund_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES orders(order_id),
  amount_fen INTEGER NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,             -- pending / completed / rejected
  created_at TEXT NOT NULL
);
CREATE TABLE returns (
  return_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL REFERENCES orders(order_id),
  item_id INTEGER NOT NULL REFERENCES order_items(item_id),
  refund_amount_fen INTEGER NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,             -- requested / approved / completed / rejected
  created_at TEXT NOT NULL
);
CREATE TABLE policies (
  policy_id TEXT PRIMARY KEY,
  category TEXT NOT NULL,           -- refund / return / delivery
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  keywords TEXT NOT NULL            -- 逗号分隔
);
"""


def connect() -> sqlite3.Connection:
    path = _DATABASE_PATH.get()
    if path is None:
        path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
