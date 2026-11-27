"""Fiber-score results (ml/fiber batch output). All read-only; `date` defaults to the latest run."""
import csv
import io
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.queries import fiber

router = APIRouter(prefix="/api/fiber", tags=["fiber"])

Date = Annotated[str | None, Query(pattern=r"^\d{4}-?\d{2}-?\d{2}$")]
Level = Literal["device", "l1", "l2"]
Order = Literal["asc", "desc"]
SuspectSort = Literal[
  "impact", "n_bad", "n_onu", "bad_share", "bad_rate_shrunk", "p_value", "med_rx", "med_excess_loss", "med_peer_delta",
  "device", "l1name", "l2name", "province", "region",
]
OnuSort = Literal["score", "rx_med", "excess_loss", "peer_delta_l2", "bip_days", "conf", "ontid", "ponport", "l2name"]
Text = Annotated[str | None, Query(max_length=100)]


def _run_or_404(fn: Any) -> Any:
  try:
    return fn()
  except fiber.RunNotFound as e:
    raise HTTPException(404, str(e)) from e


@router.get("/runs")
async def runs() -> list[dict[str, Any]]:
  return fiber.runs_payload()


@router.get("/summary")
async def summary(date: Date = None) -> dict[str, Any]:
  return _run_or_404(lambda: fiber.summary(date))


async def _suspects(date: str | None, level: str, **kw: Any) -> dict[str, Any]:
  try:
    return await fiber.suspects(date, level, **kw)
  except fiber.RunNotFound as e:
    raise HTTPException(404, str(e)) from e


@router.get("/suspects")
async def suspects(
  level: Level = "l2", date: Date = None, region: Text = None, province: Text = None, vendor: Text = None, q: Text = None,
  sort: SuspectSort = "impact", order: Order = "desc",
  page: Annotated[int, Query(ge=1, le=100000)] = 1, size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
  return await _suspects(date, level, region=region or None, province=province or None, vendor=vendor or None,
                         q=q or None, sort=sort, order=order, page=page, size=size)


CSV_COLS = {
  "device": ["device", "vendor", "model", "region", "province", "sitename", "n_onu", "n_bad", "n_l1", "n_suspect_l1",
             "bad_share", "bad_rate_shrunk", "p_value", "med_rx", "med_excess_loss", "med_peer_delta", "impact"],
  "l1": ["device", "l1name", "region", "province", "sitename", "n_onu", "n_bad", "n_l2", "n_bad_l2", "n_sibling_l1",
         "bad_share", "bad_rate_shrunk", "p_value", "med_rx", "med_excess_loss", "med_peer_delta", "impact"],
  "l2": ["device", "l1name", "l2name", "region", "province", "sitename", "n_onu", "n_bad", "n_sibling_l2",
         "bad_share", "bad_rate_shrunk", "p_value", "med_rx", "med_excess_loss", "med_peer_delta", "impact"],
}


@router.get("/suspects.csv")
async def suspects_csv(
  level: Level = "l2", date: Date = None, region: Text = None, province: Text = None, vendor: Text = None, q: Text = None,
  sort: SuspectSort = "impact", order: Order = "desc",
) -> StreamingResponse:
  res = await _suspects(date, level, region=region or None, province=province or None, vendor=vendor or None,
                        q=q or None, sort=sort, order=order, page=1, size=100_000)
  buf = io.StringIO()
  buf.write("﻿")  # BOM so Excel reads Thai province names
  w = csv.writer(buf)
  cols = CSV_COLS[level]
  w.writerow(cols)
  for r in res["items"]:
    w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
  name = f"fiber-suspect-{level}-{res['date']}.csv"
  return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                           headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def _or_404(coro: Any, what: str) -> Any:
  try:
    res = await coro
  except fiber.RunNotFound as e:
    raise HTTPException(404, str(e)) from e
  if res is None:
    raise HTTPException(404, f"{what} not found")
  return res


@router.get("/devices/{device_id}/tree")
async def device_tree(device_id: int, date: Date = None) -> dict[str, Any]:
  """PON (L1) -> L2 aggregates of one OLT's fiber scores."""
  return await _or_404(fiber.device_tree(date, device_id), "device")


@router.get("/devices/{device_id}/onus")
async def device_onus(
  device_id: int, date: Date = None, ponport: Text = None, l1name: Text = None, l2name: Text = None,
  max_score: Annotated[int | None, Query(ge=1, le=10)] = None,
  sort: OnuSort = "score", order: Order = "asc",
  page: Annotated[int, Query(ge=1, le=100000)] = 1, size: Annotated[int, Query(ge=1, le=fiber.MAX_PAGE)] = 50,
) -> dict[str, Any]:
  return await _or_404(fiber.device_onus(date, device_id, ponport or None, l1name or None, l2name or None, max_score,
                                         sort, order, page, size), "device")


@router.get("/onus")
async def bad_onus(
  attributed_to: Literal["drop", "l2", "l1", "device", "onu_hw"],
  date: Date = None, q: Text = None,
  sort: Literal[OnuSort, "device"] = "score", order: Order = "asc",
  page: Annotated[int, Query(ge=1, le=100000)] = 1, size: Annotated[int, Query(ge=1, le=fiber.MAX_PAGE)] = 50,
) -> dict[str, Any]:
  """Bad ONUs across all OLTs with one likely location (attribution)."""
  try:
    return await fiber.bad_onus(date, attributed_to, q or None, sort, order, page, size)
  except fiber.RunNotFound as e:
    raise HTTPException(404, str(e)) from e


@router.get("/devices/{device_id}/ponports")
async def ponport_scores(device_id: int, date: Date = None) -> dict[str, Any]:
  """{ponport: {n_onu, n_bad, min_score}} for score badges on the PON-port table."""
  return await _or_404(fiber.ponport_scores(date, device_id), "device")


@router.get("/devices/{device_id}/onu")
async def onu(
  device_id: int,
  ponport: Annotated[str, Query(min_length=1, max_length=100)],
  ontid: Annotated[str, Query(min_length=1, max_length=50)],
  date: Date = None,
) -> dict[str, Any]:
  """One ONU's full score row plus its daily Rx/BIP history from the lake."""
  try:
    d = await fiber.onu_detail(date, device_id, ponport, ontid)
  except fiber.RunNotFound as e:
    raise HTTPException(404, str(e)) from e
  if d is None:
    name = await fiber.device_name(device_id)
    raise HTTPException(404, await fiber.unscored_reason(date, name, ponport, ontid) if name else "device not found")
  return d
