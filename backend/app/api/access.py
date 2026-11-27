"""Access-id (circuit number) lookup: subscriber ONU, its OLT/PON/ODN path, fiber score and trouble tickets."""
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query

from app.queries import access

router = APIRouter(prefix="/api/access", tags=["access"])


@router.get("/{accessid}")
async def lookup(
  accessid: Annotated[str, Path(min_length=4, max_length=60)],
  tickets: Annotated[int, Query(ge=0, le=access.MAX_TICKETS)] = 10,
) -> dict[str, Any]:
  try:
    r = await access.lookup(accessid, tickets)
  except ValueError as e:
    raise HTTPException(422, str(e)) from e
  if r is None:
    raise HTTPException(404, f"No ONU with access id {accessid.strip()}")
  return r
