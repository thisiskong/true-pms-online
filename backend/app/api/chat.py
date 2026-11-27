import json
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.chat import orchestrator, sessions

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
  session_id: str | None = Field(None, max_length=64)
  message: str = Field(..., min_length=1, max_length=4000)
  device_id: int | None = Field(None, description="Device the user is currently viewing (optional context)")
  model: str | None = Field(None, max_length=100, description="One of GET /api/chat/models; default when omitted")


@router.post("")
async def chat(req: ChatRequest) -> StreamingResponse:
  """One chat turn, streamed as Server-Sent Events (event name = payload `type`)."""
  async def gen() -> AsyncIterator[str]:
    async for ev in orchestrator.run_turn(req.session_id, req.message, req.device_id, req.model):
      yield f"event: {ev['type']}\ndata: {json.dumps(ev, default=str, ensure_ascii=False)}\n\n"

  return StreamingResponse(
    gen(), media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
  )


@router.get("/models")
async def models() -> dict:
  """Models the user may pick in the chat, with display names and prices when known."""
  return await orchestrator.list_models()


@router.delete("/{session_id}")
async def reset(session_id: str) -> dict[str, bool]:
  return {"deleted": sessions.delete(session_id)}
