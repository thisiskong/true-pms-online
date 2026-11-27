"""Fleet-wide interface list: GET /api/interfaces (+ /facets for the dropdowns)."""
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query

from app.queries import intf_fleet

router = APIRouter(prefix="/api/interfaces", tags=["interfaces"])

Text = Annotated[str | None, Query(max_length=100)]


@router.get("")
async def list_interfaces(
  device: Text = None, q: Text = None, ifoper: Text = None, dsttype: Text = None, moduleclass: Text = None,
  sort: Annotated[str, Query(max_length=20)] = "name",
  order: Literal["asc", "desc"] = "asc",
  page: Annotated[int, Query(ge=1, le=100000)] = 1,
  size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
  """device = device name substring or IP prefix; q = text in interface name/altname/ifname/description/dstsite/dstport."""
  return await intf_fleet.list_interfaces(device, q, ifoper, dsttype, moduleclass, sort, order, page, size)


@router.get("/facets")
async def facets() -> dict[str, Any]:
  return await intf_fleet.facets()
