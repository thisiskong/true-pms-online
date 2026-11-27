"""Stage 1: cleanse daily metrics and ODN inventory.

Each metric field becomes a clean column plus a dq_<field> reason code
('sentinel' or 'range') whenever the raw value was nulled.
"""

from common import log, part, sql_path, write_parquet

# clean name -> raw column
METRIC_FIELDS = {
  "rx": "onu_rxpwr",
  "tx": "onu_txpwr",
  "voltage": "onu_voltage",
  "temp": "onu_temp",
  "current": "onu_current",
  "bip_in": "onu_in_biperr",
  "bip_out": "onu_out_biperr",
  "ranging": "ranging",
  "lostcarrier": "radius_lostcarrier",
}

MODULECLASS_SQL = """
  case
    when moduleclass is null then 'unknown'
    when lower(moduleclass) like '%invalid%' then 'unknown'
    when lower(moduleclass) like '%cplusplus%' or moduleclass like '%C++%' then 'C++'
    when lower(moduleclass) like '%cplus%' or moduleclass like '%C+%' then 'C+'
    when lower(moduleclass) like '%bplus%' or moduleclass like '%B+%' then 'B+'
    when lower(moduleclass) like '%class d%' then 'D'
    else 'unknown'
  end
"""


def _sentinel_sql(name, x, s):
  if name == "rx":
    return f"{x} <= {s['rx_at_or_below']}"
  if name == "tx":
    return f"{x} <= {s['tx_at_or_below']}"
  if name == "current":
    return f"{x} < {s['current_below']}"
  if name == "temp":
    lo, hi = s["temp_neg_band"]
    return f"{x} >= {lo} and {x} < {hi} and onu_current < {s['current_below']}"
  return "false"


def cleanse_metrics(con, d, cfg, force=False):
  src, dst = part("onu_pon_1d", d), part("clean_onu", d)
  if dst.exists() and not force:
    return dst
  if not src.exists():
    return None
  s, valid, hw = cfg["sentinels"], cfg["valid"], cfg["hw_ok"]
  fix = cfg["voltage_unit_fix_below"]

  stage_a, stage_b = [], []
  for name, raw in METRIC_FIELDS.items():
    v = f"case when {raw} < {fix} then {raw} * 1000 else {raw} end" if name == "voltage" else raw
    lo, hi = valid[name]
    stage_a.append(f"{v} as {name}_v")
    stage_a.append(
      f"case when {raw} is null then null when {_sentinel_sql(name, raw, s)} then 'sentinel' "
      f"when not ({v} between {lo} and {hi}) then 'range' end as dq_{name}"
    )
    stage_b.append(f"case when dq_{name} is null then {name}_v end as {name}")

  hw_terms = " or ".join(
    f"coalesce(not ({n} between {lo} and {hi}), false)" for n, (lo, hi) in hw.items()
  )
  dq_cols = ", ".join(f"dq_{n}" for n in METRIC_FIELDS)
  sql = f"""
    with m as (
      select * from read_parquet({sql_path(src)})
      qualify row_number() over (partition by tstamp, device, ponport, ontid) = 1
    ),
    a as (
      select tstamp, device, ponport, ontid, vendor, model, moduleclass,
             {MODULECLASS_SQL} as moduleclass_n, l1name, l2name,
             onu_voltage < {fix} as fix_voltage,
             {", ".join(stage_a)}
      from m
    ),
    b as (
      select tstamp, device, ponport, ontid, vendor, model, moduleclass, moduleclass_n, l1name, l2name,
             fix_voltage, {", ".join(stage_b)}, {dq_cols}
      from a
    )
    select *, ({hw_terms}) as hw_flag
    from b
    where rx is not null or bip_in is not null or bip_out is not null or lostcarrier is not null
  """
  log(f"cleanse metrics {d}")
  return write_parquet(con, sql, dst)


def cleanse_odn(con, d, cfg, force=False):
  src, dst = part("odn_onu", d), part("clean_odn", d)
  if dst.exists() and not force:
    return dst
  if not src.exists():
    return None
  v = cfg["valid"]

  def rng(c):
    lo, hi = v[c]
    return f"case when {c} between {lo} and {hi} then {c} end as {c}"

  sql = f"""
    with o as (
      select * from read_parquet({sql_path(src)})
      qualify row_number() over (partition by device, ponport, ontid) = 1
    ),
    multi as (
      select l2name from o where l2name is not null group by l2name having count(distinct device) > 1
    )
    select o.device, o.ponport, o.ontid, o.l1name, o.l2name,
           {rng("l1len")}, {rng("l2len")}, l1ratio, l2ratio, {rng("splitratio")},
           multi.l2name is not null as dq_l2_multi_device
    from o left join multi using (l2name)
  """
  log(f"cleanse odn {d}")
  return write_parquet(con, sql, dst)
