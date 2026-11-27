# Fiber Score: ML Pipeline Design

**Goal:** give every ONU (`device|ponport|ontid`) a fiber score from 1 to 10. 1 means poor fiber quality and 10 means excellent. Then roll the scores up the ODN tree (`device → l1name → l2name → ONU`) to find the shared fiber segments most likely causing quality problems.

**Inputs:**
- `data/onu_pon_1d_YYYYMMDD.jsonl`: daily ONU metrics, one row per ONU per day.
- `data/odn_onu_YYYYMMDD.jsonl`: passive inventory (L1/L2 splitter names, segment lengths, split ratios).

Every number below comes from profiling the 2026-11-20 snapshot: 3.32M metric rows, 3.39M inventory rows, 12.5K devices, 162K PON ports, 686K L2 splitters.

---

## 1. What the data says (profiling findings)

These findings drive the cleansing rules and thresholds.

| Finding | Evidence | Consequence |
|---|---|---|
| Downstream Rx power is the strongest fiber signal. | `onu_in_biperr > 0` affects 0.5% of ONUs at −18 dBm, 3% at −25, 5% at −27, 8% at −28, 18% at −29 and 42% at −30. | The sensitivity knee is about **−28 dBm**, which matches the GPON Class B+ spec (−27/−28). |
| Overload starts above about −9 dBm. | The error rate rises again: 7% at −9 and 30% at −7. | Treat Rx above −9 dBm as a problem too (missing attenuator or short link). |
| `onu_in_biperr` tracks Rx and `onu_out_biperr` does not. | Correlation with Rx is −0.17 for in and +0.05 for out. Out errors peak at −16 dBm, which is unrelated to signal. | Use `in_biperr` as the fiber error signal. Keep `out_biperr` only as context until it is understood per vendor. |
| Rx falls with fiber length at about the physical rate. | Slope −0.24 dB/km, close to the 0.25 dB/km expected at 1490 nm. Median Rx drops from −19.0 dBm (0–2 km) to −21.5 dBm (10–12 km). | Length is usable for an expected-loss model. |
| Rx falls with split ratio much less than physics predicts. | −0.22 dB per dB of split loss, against about 1.0 expected. | `splitratio` is noisy or is offset by OLT optics class. Learn it from data instead of using theory. |
| Sentinel values for "not reported". | `txpwr = −40` (138K rows), `temp ≈ −1.2` (140K), `current ≈ −0.98` (140K), `rxpwr = −255`. These rows still have a valid Rx (median −20.7). | Convert the sentinels to null per field. Do not drop the row. |
| Voltage unit bug. | 234K rows have voltage around 0.0032. That is 3.2 V divided by 1000. | Multiply values below 1 by 1000. |
| Counter wrap or garbage values. | `in_biperr` max is 1.8e19 (a uint64 wrap). Other maxima are absurd: Rx 735, Tx 17373, temp 17884. | Null anything outside the physically valid range (§2). |
| RADIUS columns cover only 21% of ONUs. | 699K of 3.32M rows have them. `radius_porterror` is always 0. | RADIUS data is an optional feature. Only `lostcarrier` relates to fiber. |
| GCOM and Raisecom have no BIP counters. | 0 non-null `biperr` values for both. | The scorer must handle missing sub-scores per vendor. |
| `moduleclass` is not standardised across vendors. | Examples: `gpon-classbplus`, `GPON/B+`, `classbplus`, `GPON CLASS B+ SFP OLT`, `gponandxgspon-invalid`. 414K rows are null. | Normalise it to {B+, C+, C++, D, unknown}. It sets the OLT launch power, so it matters for expected Rx. |
| Join coverage is 99.74%. | 8.6K metric rows have no inventory row. The two files disagree on l1name in 197 rows and on l2name in 394. | Take topology from `odn_onu` and flag the disagreements. |
| `l1name` maps almost 1:1 to a PON port. | 162,226 L1 names for 162,225 PON ports. A median PON has 18 ONUs and a median L2 has 5. | From topology alone, an L1 fault can't be told apart from an OLT PON optic fault (§6). |
| 140 L2 names appear under more than one device. | | Inventory error. Flag these and exclude them from L2 attribution. |

---

## 2. Acceptable range for each metric

There are two ranges per metric:
- **Valid range:** outside it the value is a sensor or collection error. Set it to null.
- **Acceptable range:** outside it the value is real but indicates a problem.

| Metric | Unit | Valid range (else null) | Acceptable | Warning | Bad | Used for |
|---|---|---|---|---|---|---|
| `onu_rxpwr` | dBm | −40 … 0 | −9 … −25 | −25 … −28 | < −28, or > −9 (overload) | **Fiber score (primary)** |
| `onu_txpwr` | dBm | −10 … 10 (−40 is a sentinel) | 0.5 … 5 | 5 … 7 | outside 0.5 … 7 | ONU hardware flag, not the fiber score |
| `onu_voltage` | V | 2.5 … 4.0 after ×1000 for values < 1 | 3.135 … 3.465 | ±10% | outside 3.0 … 3.6 | ONU hardware flag |
| `onu_temp` | °C | −40 … 110 (≈ −1.2 is a sentinel) | 0 … 70 | 70 … 80 | > 80 | ONU hardware flag |
| `onu_current` (laser bias) | mA | 0 … 100 (≈ −1 is a sentinel) | 3 … 40 | 40 … 60 | > 60 | ONU hardware flag |
| `onu_in_biperr` | count/day | 0 … 1e12 (above is a counter wrap) | 0 | 1 … 1000 | > 1000, or > 0 on 3 or more days of a 7-day window | **Fiber score** |
| `onu_out_biperr` | count/day | 0 … 1e12 | 0 | — | — | Context only, until validated |
| `ranging` | m | 0 … 60,000 | ≤ 20,000 (GPON logical reach) | 20 … 40 km | > 40 km | Cross-check against `l1len + l2len` |
| `radius_lostcarrier` | count/day | 0 … 1,000 | 0 … 1 | 2 … 5 | > 5 | **Fiber score (stability)**, when present |
| other `radius_*` | count/day | 0 … 10,000 | — | — | — | Excluded: they record user or BRAS events, not fiber |
| `l1len`, `l2len` | m | 0 … 40,000 | — | — | — | Expected-loss model |
| `splitratio` | 1:N | 2 … 128 | — | — | — | Expected-loss model |

All thresholds live in `ml/fiber/ranges.yaml`, not in code, so they can be retuned. The Rx thresholds were set from the error-rate curve in §1. Re-derive them per `moduleclass` once more days of data are available.

---

## 3. Pipeline overview

```
 export_jsonl.py (daily)
        │
 ┌──────▼──────┐   ┌───────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐
 │ 0. Ingest   │──▶│ 1. Cleanse│──▶│ 2. Daily    │──▶│ 3. Window    │──▶│ 4. Expected  │──▶│ 5. Score    │
 │ jsonl→parq. │   │ + join ODN│   │  features   │   │  aggregates  │   │ loss model   │   │  1–10/ONU   │
 └─────────────┘   └───────────┘   └─────────────┘   │ (7d / 30d)   │   │ (residuals)  │   └──────┬──────┘
                                                      └──────────────┘   └──────────────┘          │
                                                                                          ┌───────▼───────┐
                                                                                          │ 6. Attribution│
                                                                                          │ device/L1/L2  │
                                                                                          └───────────────┘
```

**Engine:** DuckDB over Parquet, using the same approach as the profiling above. It handles 3.3M rows a day on a laptop in seconds, and 30 days (about 100M rows) is still fine. Use Polars where row-wise Python is needed. The Postgres database stays read-only, and all outputs are files.

**Proposed layout:**
```
ml/
  export_jsonl.py          # existing: daily pull from Postgres
  fiber/
    ranges.yaml            # §2 thresholds, weights, sentinels
    ingest.py              # stage 0
    cleanse.py             # stage 1
    features.py            # stages 2–3
    expected_loss.py       # stage 4
    score.py               # stage 5
    attribute.py           # stage 6
    run.py                 # orchestrates: uv run fiber/run.py --date 2026-11-20 --window 7
  data/                    # raw jsonl (git-ignored)
  lake/                    # parquet, partitioned by date (git-ignored)
  out/                     # scores and suspect lists (git-ignored)
```

---

## 4. Stages

### Stage 0: Ingest
- Convert each day's JSONL to Parquet at `lake/onu_pon_1d/date=YYYY-MM-DD/` and `lake/odn_onu/date=YYYY-MM-DD/`. The Parquet files are about 10× smaller and columnar.
- Enforce the schema: cast `ontid` to string, cast counters to double (they may be fractional because they are averaged), and cast `tstamp` to date.

### Stage 1: Cleanse
Apply these steps in order. Each nulled field writes a `dq_<field>` reason code, so the data-quality rates can be monitored over time.

1. **Dedupe** on `(tstamp, device, ponport, ontid)` and keep the last row.
2. **Sentinels to null:**
   - `txpwr ≤ −39`
   - `rxpwr ≤ −50`
   - `temp ∈ [−2, 0)` together with `current < 0`
   - `current < 0`
3. **Unit fix:** where `voltage < 1`, set `voltage × 1000`.
4. **Valid range:** null any value outside the valid range in §2. This covers counter wraps and absurd maxima.
5. **Normalise `moduleclass`** with a lookup table:
   - `*bplus*` / `*B+*` → `B+`
   - `*cplusplus*` / `C++` → `C++`
   - `*cplus*` / `C+` → `C+`
   - `Class D` → `D`
   - anything else, including `*invalid*` → `unknown`
6. **Join to ODN** on `(device, ponport, ontid)`, taking topology from `odn_onu`. Then set flags:
   - `dq_no_odn`: no inventory row (0.26%).
   - `dq_topo_mismatch`: the files disagree on l1name or l2name.
   - `dq_l2_multi_device`: one of the 140 inconsistent L2 names.
7. **Drop the row** only when Rx is null and every BIP and RADIUS field is also null. Such a row has no fiber signal.

### Stage 2: Daily features (per ONU per day)
- `rx`: cleaned `onu_rxpwr`.
- `rx_margin = rx − sens`: distance to sensitivity. `sens` is −28 for B+ and C+ (from config).
- `overload = rx > −9`.
- `bip_in_log = log10(1 + onu_in_biperr)` and `bip_in_flag = onu_in_biperr > 0`.
- `lostcarrier = radius_lostcarrier`. This is often null.
- `len_km = (l1len + l2len) / 1000` and `split_db = 10·log10(splitratio)`.
- `range_mismatch = |ranging − (l1len + l2len)| > 2 km`. This is an inventory-quality flag, not part of the score.
- `hw_flag`: Tx, voltage, temp or bias current outside the acceptable range. If an ONU's own laser or board is failing, the problem isn't the fiber. Keep it out of the fiber score and report it separately.

### Stage 3: Window aggregates (per ONU, 7-day window; also 30-day)
- `rx_med`, `rx_p10`: median Rx, plus the low tail, which catches intermittent fades.
- `rx_sd`: day-to-day volatility. Healthy fiber is stable, so a high value points to a bend, a dirty connector or a moving fault.
- `rx_slope`: dB/day from linear regression. A negative trend means degradation.
- `bip_days`: number of days with `in_biperr > 0`. Also `bip_log_mean`.
- `lc_days`, `lc_sum`: lost-carrier events.
- `days_obs`: coverage. It feeds the confidence value.

> The snapshot currently on disk covers one day, so `rx_sd`, `rx_slope` and `bip_days` can't be computed yet. Run `export_jsonl.py --date` daily, or back-fill 7–30 days. Until then the scorer runs in **single-day mode**: stability features are absent and their weight is redistributed (§5).

### Stage 4: Expected-loss model (the ML part)
Raw Rx alone confounds a bad fiber with a long fiber, a high split ratio or a weak OLT optic. Learn what Rx *should* be for this ONU's path, then score the shortfall.

**Expected Rx model:**
```
rx_med ~ f(moduleclass, vendor, split_db, len_km, l1ratio, l2ratio)
```
- Use a gradient-boosted regressor (LightGBM) with a Huber loss, so the faults themselves don't pull the fit.
- Alternative: a robust linear model, which is easier to explain. Fitted on this snapshot it gives about −0.24 dB/km and −0.22 dB per split-dB.
- Train it on ONUs that have `bip_days = 0`, no `hw_flag` and no `dq_*` flags. That set is "presumed healthy".

**Two residuals per ONU:**
- `excess_loss = expected_rx − rx_med` (dB). Positive means more loss than the path explains. This is the fiber-score input.
- `peer_delta = rx_med − median(rx_med of the other ONUs on the same L2)`, and likewise for the same L1. This is the attribution input. A large negative value for one ONU among healthy siblings points to its drop cable or connector. When the whole group is shifted, the fault is upstream.

**Validation:** hold out 20% of PON ports, not individual rows, so the model can't learn a port's OLT optic. Target MAE below 1.5 dB.

### Stage 5: Score (1–10 per ONU)
Compute four sub-scores, each from 0 to 1, using piecewise-linear maps over the §2 bands.

| Sub-score | Input | 1.0 | 0.5 | 0.0 | Weight |
|---|---|---|---|---|---|
| `s_power` | `rx_med`, or `rx_p10` when the window allows | −9 … −22 dBm | −26 dBm | ≤ −30 dBm, or ≥ −6 (overload) | 0.40 |
| `s_excess` | `excess_loss` | ≤ 1 dB | 3 dB | ≥ 6 dB | 0.25 |
| `s_error` | `bip_days`, `bip_log_mean` (in only) | 0 errors | errors on 1 day, or < 1e3/day | errors every day, or > 1e5/day | 0.20 |
| `s_stability` | `rx_sd`, `rx_slope`, `lc_days` | sd < 0.5, slope ≥ −0.05 dB/day, no lost-carrier events | sd 1.5 | sd > 3, slope < −0.3, or lost carrier on most days | 0.15 |

**Combining them:**
```
S      = Σ wᵢ·sᵢ / Σ wᵢ              # over sub-scores that are present (renormalise when GCOM/Raisecom lack BIP, or there is no RADIUS or no window)
score  = round(1 + 9·S)             # 1..10
caps   : rx_med < −28  → score ≤ 3   # below sensitivity: hard fail regardless of the other sub-scores
         rx_med < −30  → score = 1
         bip on every day in the window → score ≤ 5
conf   = (Σ wᵢ present) × min(1, days_obs / window)   # 0..1, published next to the score
```

**Why fixed bands instead of quantile scaling:** a score of 6 should mean the same thing next month. Quantile scaling would always label 10% of ONUs as "1" even if the whole network improves.

**Why rules plus regression instead of a fully supervised model:** there are no fault labels yet. A supervised model trained on this data would only learn the thresholds back. See §7 for the upgrade path.

**Rough expectation from this snapshot:**
- 1.5% of ONUs have Rx below −27.
- 0.03% are in overload.
- About 1.2% have `in_biperr > 0`.

So roughly 2–3% of ONUs should land at a score of 5 or below. Check the score histogram after the first run.

### Stage 6: Attribution to device, L1 and L2
The question is which shared segment explains the bad ONUs.

For each node at each level (device, L1 ≈ PON, L2), compute:
- `n_onu`, and `n_bad` = ONUs with score ≤ 4.
- `bad_rate_shrunk = (n_bad + α·p₀) / (n_onu + α)`. This is beta-binomial shrinkage toward the global bad rate `p₀`, with α of about 10. A median L2 has only 5 ONUs, so without shrinkage one bad ONU out of 2 would top the list.
- `p_value`: a one-sided binomial test of `n_bad` against `p₀·n_onu`.
- `med_peer_delta`: the group's median Rx shift relative to its siblings. For an L2, compare it with the other L2s under the same L1. For an L1, compare it with the other PONs on the same device.
- `med_excess_loss`.

**Localisation rule, applied top-down:**

| Pattern | Likely location |
|---|---|
| Most PONs on the device are bad | **OLT/device**: optics batch, configuration, or the site's power and temperature. Report it, but it's not a fiber fault. |
| One L1 is bad, its sibling L1s are fine, and the bad ONUs are spread across its L2s | **L1 feeder fiber or L1 splitter**. The OLT PON SFP is also possible, because L1 maps 1:1 to the PON. Separate the two by checking upstream errors on the OLT side, or by seeing whether the problem moves when the SFP is replaced. |
| One L2 is bad, its sibling L2s under the same L1 are fine, and `med_peer_delta` is ≤ −3 dB | **L2 splitter or distribution fiber** |
| Isolated bad ONUs whose siblings are healthy | **Drop cable, connector or ONU**. Check `hw_flag` first. |

Assign each bad ONU to the **highest** level that explains it, so ONUs aren't double-counted. This produces ranked suspect lists per level, ordered by `n_bad × med_excess_loss` (an impact estimate).

---

## 5. Outputs

| File | Grain | Key columns |
|---|---|---|
| `out/onu_fiber_score_YYYYMMDD.parquet` | ONU | key, l1name, l2name, vendor, `score`, `conf`, `s_power`/`s_excess`/`s_error`/`s_stability`, `rx_med`, `excess_loss`, `peer_delta`, `hw_flag`, `dq_*`, `attributed_to` |
| `out/suspect_l2_YYYYMMDD.csv` | L2 | l2name, l1name, device, n_onu, n_bad, bad_rate_shrunk, p_value, med_peer_delta, med_excess_loss, impact |
| `out/suspect_l1_YYYYMMDD.csv` | L1 / PON | same columns |
| `out/suspect_device_YYYYMMDD.csv` | device | same columns |
| `out/dq_report_YYYYMMDD.json` | run | null and sentinel rates per field and vendor, join coverage, topology mismatches |

These files can later be loaded into a Postgres table, after a schema change made outside the app (DDL is external), and shown in the webapp.

---

## 6. Known limitations

- **L1 vs OLT optic:** L1 maps 1:1 to the PON port, so the ONU data alone can't separate a dirty or weak OLT SFP from a bad feeder fiber. Adding OLT-side upstream Rx per ONU (if it's collected) would resolve this. A weak *OLT launch* lowers every ONU's Rx equally, while a feeder fault adds loss only downstream of the fault.
- **Only one direction is measured.** ONU Rx is downstream at 1490 nm. Some faults, such as macro-bends, hurt 1550/1625 nm more. Upstream OLT Rx at 1310 nm would add a second, independent view.
- **Split ratio coefficient:** the weak learned coefficient (−0.22 against the theoretical −1.0) suggests that `splitratio` in `odn_onu` is often wrong. Rank ONUs with a large `|excess_loss|` but no errors as candidates for an inventory audit.
- **A single day can't show degradation trends.** Back-fill history first.

---

## 7. Roadmap

1. **Phase 1 (this design):** cleansing, rules plus the expected-loss residual, a 1–10 score and attribution. Fully explainable, so each score can be traced to its sub-scores.
2. **Phase 2, calibration:** join with trouble tickets or fiber-repair records (from TT or NOC). Check that the 30-day ticket rate falls steadily from score 1 to score 10, and retune bands and weights to maximise ticket-ranking AUC.
3. **Phase 3, supervised:** with labels, train `P(fiber fault within 30 days)` on the window features using LightGBM, then map calibrated probability deciles to scores. Keep the Phase 1 score as a baseline and for explanation, using SHAP for the model.
4. **Optional, anomaly cross-check:** run an Isolation Forest per vendor over `(rx_med, rx_sd, bip_log_mean, excess_loss)` to surface odd ONUs that the rules miss.

---

## 8. Validation checklist for the first real run

- [ ] DQ report: sentinel and null rates per vendor match §1 (about 4% Tx sentinel, about 7% voltage unit fix).
- [ ] Score histogram: the bulk sits at 8–10 and roughly 2–3% are at 5 or below.
- [ ] Mean `in_biperr > 0` rate falls steadily from score 1 to score 10.
- [ ] Expected-loss model MAE below 1.5 dB on held-out PONs.
- [ ] Spot-check the top 20 L2 suspects with the field or NOC team.

---

## 9. Implementation and first run (2026-11-20, single day)

Code lives in `ml/fiber/`; thresholds in `ml/fiber/ranges.yaml`. Run from `ml/`:

```
uv run fiber/run.py --date 2026-11-20            # default 7-day window; uses whatever days are in data/
```

First run, 1 day of data, 3,297,747 ONUs, 47 s on a laptop:

| Check | Result |
|---|---|
| Score histogram | 10: 73.4%, 9: 10.9%, 8: 6.4%, 7: 4.0%, 6: 2.4%, 5: 1.3%, 1–4: 1.6% |
| Bad ONUs (score ≤ 4) | 53,206 (1.6%) |
| Share of ONUs with BIP errors, by score | 72–100% at 1–2, 20–22% at 3–4, 3–7% at 5–9, 0.4% at 10. Falls with score as intended. |
| Expected-Rx model | Holdout MAE **1.96 dB** against a 2.39 dB median baseline. **Misses the 1.5 dB target.** Most of the remaining error is per-PON OLT launch power, which no input captures. |
| Attribution of bad ONUs | drop: 45,673 · L2: 4,497 · L1: 3,014 · device: 16 · ONU hardware: 6 |
| Suspects | 1 device, 342 L1, 1,805 L2 |
| Confidence | About 0.11, because 1 of 7 window days is present and stability is mostly missing. It rises as days are back-filled. |
| Inventory flags | 8,275 ONUs with no ODN row, 391 topology mismatches, 509 on multi-device L2s, and 213K (6.5%) whose `ranging` differs from `l1len + l2len` by more than 2 km |

Open points:
- GCOM and Raisecom score worse: 4% bad, against 1.2–1.6% for other vendors. They have no BIP counters, and their median Rx is about 1.5 dB lower. Check whether this is real or comes from reweighting the missing sub-score.
- The model's top inputs are `moduleclass` and OLT `model`, which stand in for OLT launch power. An OLT-side Tx or upstream Rx feature is the most likely way to bring MAE under 1.5 dB.

### Production run (daily)

```
uv run fiber/export.py onu_pon_1d          # yesterday, Postgres -> lake/onu_pon_1d/date=.../part.parquet
uv run fiber/export.py odn_onu             # weekly: current inventory -> lake/odn_onu/date=<today>/
uv run fiber/run.py --date <yesterday>     # reuses models/expected_rx_*.txt up to 7 days old; --retrain to force
```

- **Export** goes straight into the lake through DuckDB's `postgres` extension, installed on the machine that runs the export. It reads the day's Postgres partition (`onu_pon_1d_pYYYYMMDD00`) over 4 read-only connections. Each day is about 120 MB of Parquet instead of 2 GB of JSONL, and takes 56–99 s instead of 96–215 s. The database is the bottleneck. 14 connections took 26 s but put more load on it.
- **Model reuse:** a 7-day run takes 59 s with a saved model, against 115 s when it trains. Every run measures holdout MAE on that day's data and warns if it drifts more than 0.3 dB above the training MAE.
- **7-day run (ending 2026-11-23):** mean confidence 0.90, up from 0.11 for a single day. 41,717 bad ONUs. Suspects: 1 device, 191 L1, 1,259 L2.
