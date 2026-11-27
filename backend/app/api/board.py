"""Fleet-wide board list: GET /api/boards (+ /facets for the dropdowns)."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.queries import board

router = APIRouter(prefix="/api/boards", tags=["boards"])

Text = Annotated[str | None, Query(max_length=100)]


@router.get("")
async def list_boards(
  device: Text = None, q: Text = None, boardtype: Text = None, boardrole: Text = None, operstatus: Text = None,
  sort: Annotated[str, Query(max_length=20)] = "device_name",
  order: Literal["asc", "desc"] = "asc",
  page: Annotated[int, Query(ge=1, le=100000)] = 1,
  size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
  """device = device name substring or IP prefix; q = text in board name/type/role."""
  filters = {"boardtype": boardtype, "boardrole": boardrole, "operstatus": operstatus}
  return await board.list_boards(device, q, filters, sort, order, page, size)


@router.get("/facets")
async def facets() -> dict[str, Any]:
  return await board.facets()
