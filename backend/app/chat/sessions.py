"""In-memory conversation store (prototype). Never stored in the pmsonline database."""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings


@dataclass
class Session:
  id: str
  messages: list[dict[str, Any]] = field(default_factory=list)
  updated: float = field(default_factory=time.monotonic)
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  model: str | None = None  # model that answered the last turn


_sessions: dict[str, Session] = {}


def _gc() -> None:
  ttl = get_settings().chat_session_ttl_s
  now = time.monotonic()
  for sid in [k for k, s in _sessions.items() if now - s.updated > ttl and not s.lock.locked()]:
    _sessions.pop(sid, None)


def get_or_create(session_id: str | None) -> Session:
  _gc()
  if session_id and session_id in _sessions:
    s = _sessions[session_id]
  else:
    s = Session(id=session_id or uuid.uuid4().hex)
    _sessions[s.id] = s
  s.updated = time.monotonic()
  return s


def delete(session_id: str) -> bool:
  return _sessions.pop(session_id, None) is not None
