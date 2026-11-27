"""Stages 2-3: per-ONU window aggregates joined to ODN topology, plus peer deltas."""

import datetime as dt

from common import log, part, sql_path


def window_dates(d, window):
  """Dates in [d - window + 1, d] that have cleansed metrics on disk."""
  days = [d - dt.timedelta(days=i) for i in range(window)]
  return sorted(x for x in days if part("clean_onu", x).exists())


def build_features(con, d, window, odn_path, cfg):
  """Return a DataFrame with one row per ONU for the window ending on d."""
  dates = window_dates(d, window)
  if d not in dates:
    raise SystemExit(f"no cleansed metrics for {d}")
  files = "[" + ", ".join(sql_path(part("clean_onu", x)) for x in dates) + "]"
  min_days = cfg["min_days_for_trend"]
  hw_share = cfg["hw_flag_min_share"]
  # ONU hardware readings: window median, and days outside the hw_ok range (shows which reading set hw_flag).
  hw_cols = ", ".join(
    f"round(median({n}), 3) as {n}_med, count({n}) as {n}_obs, count_if(not ({n} between {lo} and {hi})) as hw_{n}_days"
    for n, (lo, hi) in cfg["hw_ok"].items()
  )
  log(f"features: {len(dates)} day(s) {dates[0]} .. {dates[-1]}")

  sql = f"""
    with daily as (
      select * from read_parquet({files})
    ),
    w as (
      select device, ponport, ontid,
        arg_max(vendor, tstamp) as vendor,
        arg_max(model, tstamp) as model,
        arg_max(moduleclass_n, tstamp) as moduleclass,
        arg_max(l1name, tstamp) as m_l1name,
        arg_max(l2name, tstamp) as m_l2name,
        count(*) as days_obs,
        count(rx) as rx_days,
        median(rx) as rx_med,
        case when count(rx) >= {min_days} then quantile_cont(rx, 0.1) end as rx_p10,
        case when count(rx) >= {min_days} then stddev_samp(rx) end as rx_sd,
        case when count(rx) >= {min_days} then regr_slope(rx, epoch(tstamp) / 86400.0) end as rx_slope,
        count(bip_in) as bip_obs,
        count_if(bip_in > 0) as bip_days,
        avg(log10(1 + bip_in)) as bip_log_mean,
        avg(log10(1 + bip_out)) as bip_out_log_mean,
        count(lostcarrier) as lc_obs,
        count_if(lostcarrier > 0) as lc_days,
        sum(lostcarrier) as lc_sum,
        avg(lostcarrier) as lc_mean,
        arg_max(ranging, tstamp) as ranging,
        avg(hw_flag::int) >= {hw_share} as hw_flag,
        count_if(hw_flag) as hw_days,
        {hw_cols}
      from daily
      group by device, ponport, ontid
    ),
    o as (select * from read_parquet({sql_path(odn_path)})),
    j as (
      select w.*,
        coalesce(o.l1name, w.m_l1name) as l1name,
        coalesce(o.l2name, w.m_l2name) as l2name,
        o.l1len, o.l2len, o.l1ratio, o.l2ratio, o.splitratio,
        (coalesce(o.l1len, 0) + coalesce(o.l2len, 0)) / 1000.0 as len_km_raw,
        o.l1len is not null as has_len,
        10 * log10(o.splitratio) as split_db,
        o.device is null as dq_no_odn,
        o.device is not null and (
          (w.m_l1name is not null and o.l1name is not null and w.m_l1name <> o.l1name) or
          (w.m_l2name is not null and o.l2name is not null and w.m_l2name <> o.l2name)
        ) as dq_topo_mismatch,
        coalesce(o.dq_l2_multi_device, false) as dq_l2_multi_device
      from w left join o using (device, ponport, ontid)
    )
    select * exclude (len_km_raw, has_len, m_l1name, m_l2name),
      case when has_len then len_km_raw end as len_km,
      rx_med - {cfg["rx_sensitivity"]} as rx_margin,
      rx_med > {cfg["rx_overload"]} as overload,
      case when ranging is not null and has_len
        then abs(ranging - len_km_raw * 1000) > {cfg["range_mismatch_m"]} end as range_mismatch
    from j
  """
  f = con.execute(sql).df()
  log(f"features: {len(f):,} ONUs")
  return add_peer_deltas(con, f)


def add_peer_deltas(con, f):
  """peer_delta_l2: rx_med minus the median of the *other* ONUs on the same L2 (needs 2+ peers).
  peer_delta_l1: rx_med minus the median of all ONUs on the same L1 (groups are large, so self is included)."""
  con.register("f_in", f)
  peers = con.execute("""
    with x as (
      select device, ponport, ontid, l1name, l2name, rx_med from f_in
      where rx_med is not null and l2name is not null
    ),
    l2 as (
      select a.device, a.ponport, a.ontid, median(b.rx_med) as peer_med, count(*) as peer_n
      from x a join x b
        on a.device = b.device and a.l1name = b.l1name and a.l2name = b.l2name
       and not (a.ponport = b.ponport and a.ontid = b.ontid)
      group by all
    ),
    l1 as (
      select device, l1name, median(rx_med) as l1_med
      from f_in where rx_med is not null and l1name is not null group by all
    )
    select f.device, f.ponport, f.ontid,
      case when l2.peer_n >= 2 then f.rx_med - l2.peer_med end as peer_delta_l2,
      l2.peer_n as peer_n_l2,
      f.rx_med - l1.l1_med as peer_delta_l1
    from f_in f
    left join l2 using (device, ponport, ontid)
    left join l1 using (device, l1name)
  """).df()
  con.unregister("f_in")
  return f.merge(peers, on=["device", "ponport", "ontid"], how="left")
