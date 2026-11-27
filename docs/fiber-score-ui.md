# Fiber Score in the Web App: UI and API Design

**Goal:** show the output of the fiber-score pipeline (`ml/fiber/`, see `ml/fiber_score_design.md`) in the prototype app (`frontend/` + `backend/`). Users should be able to answer three questions:

1. **Where should the field team go first?** A ranked list of suspect devices, L1 segments and L2 segments.
2. **What is wrong on this OLT?** The ODN tree for one OLT, with bad ONUs placed on it.
3. **Why did this ONU get this score?** Sub-scores, caps, the expected Rx compared with the measured Rx, and its history.

The score comes from rules plus a regression model, so every number can be explained. The UI should always show the *why* next to the *what*.

---

## 1. What the pipeline produces (run 2026-11-23, 7-day window)

| File | Rows | Use in the UI |
|---|---|---|
| `out/onu_fiber_score_YYYYMMDD.parquet` (340 MB) | 3.37M ONUs, 45 columns | ONU table, ONU detail, per-OLT tree aggregates |
| `out/suspect_device_*.parquet` | 1 | Suspects table, Device level |
| `out/suspect_l1_*.parquet` | 191 | Suspects table, L1/PON level |
| `out/suspect_l2_*.parquet` | 1,259 | Suspects table, L2 level |
| `out/dq_report_*.json` | 1 run | Run header, histogram, attribution breakdown, model card, data-quality panel |
| `lake/clean_onu/date=*/` | daily | 7-day Rx/BIP sparkline for one ONU |

Headline numbers from this run: 41,717 bad ONUs (1.24%). By attribution they split into 36,647 drop, 3,126 L2, 1,920 L1, 18 device and 6 ONU hardware. Mean confidence is 0.90. Model holdout MAE is 1.94 dB, which misses the 1.5 dB target.

Suspect device names (for example `SRB13002G00`) match `device.name` in Postgres, which gives us `device.id`, region, province and site for linking and filtering.

---

## 2. Serving the data (backend)

**Read the files with DuckDB inside the backend. Do not load them into Postgres yet.**

- The database is read-only and DDL is managed externally, so a Postgres table would need an outside schema change first. Files avoid that and keep the ML and the app decoupled. Moving to Postgres later (§7) changes only `app/queries/fiber.py`.
- Measured: filtering the 340 MB Parquet by `device` takes about **20 ms** in DuckDB. That is fast enough for per-OLT pages without a separate index.
- The suspect CSVs and the DQ JSON are small. Load them once per run date and cache them in memory, keyed on the run date and file mtime, using the existing `app/cache.py`.

**Configuration:** add `ML_OUT_DIR` (default `../ml/out`) and `ML_LAKE_DIR` (default `../ml/lake`) to `config.py`. The latest run is the highest `YYYYMMDD` that has both a score Parquet and a DQ report.

**Enrichment:** after loading a suspect CSV, run one `SELECT id, name, region, province, sitename FROM device WHERE name = ANY($1)` so every row carries `device_id` (for links) and region/province (for filters). Cache the result with the CSV.

**Module layout** follows the existing pattern:
```
app/queries/fiber.py   DuckDB reads (parameterised; whitelisted sort/filter columns), Postgres enrichment
app/api/fiber.py       thin REST router
app/tools/registry.py  + fiber tools (shared by chat and MCP)
```
Add `duckdb` to `pyproject.toml`. Open DuckDB connections read-only, one per request from a small pool, with `threads` capped so a heavy query can't starve the API.

### REST API (all `GET`; `date` defaults to the latest run)

| Endpoint | Returns |
|---|---|
| `/api/fiber/runs` | `[{date, window, mean_conf, bad_onus}]` for the run picker |
| `/api/fiber/summary?date=` | KPIs, score histogram, attribution counts, suspect counts, model card (MAE, drift, feature importance), DQ summary, and the delta against the previous run |
| `/api/fiber/suspects?level=device\|l1\|l2&date=&region=&province=&vendor=&q=&sort=impact&page=&size=` | Paged suspect rows, enriched with `device_id` and region |
| `/api/fiber/suspects.csv?…` | Same filters, as CSV (reuses the existing CSV export helper) |
| `/api/fiber/devices/{device_id}/tree?date=` | For one OLT: one row per L1 (PON) with `n_onu, n_bad, med_rx, med_excess_loss, suspect`, and its L2 children with the same fields |
| `/api/fiber/devices/{device_id}/onus?l1=&l2=&max_score=&attributed_to=&sort=&page=` | ONU rows for that OLT (core columns only, §4.3) |
| `/api/fiber/onu?device_id=&ponport=&ontid=&date=` | One full ONU row plus up to 30 days of daily `rx, bip_in, lostcarrier` from `lake/clean_onu` |
| `/api/fiber/score-lookup?device_id=` | `{ponport → {n_bad, min_score}}` for badges on the existing PON-port tab |

All responses are row-capped, like the existing endpoints. No endpoint accepts free-form SQL or file paths. `date` is validated against `/runs`.

---

## 3. Navigation

- Add a top-level nav item, **Fiber health** → `/fiber`, between Devices and Assistant.
- Add a new tab, **Fiber**, to the OLT device dashboard (`/devices/:id`), next to the PON-ports tab. Show it only when `topology = OLT`.
- Deep links:
  - `/fiber?level=l2&region=Central`: suspects with filters kept in the URL, like the device list.
  - `/devices/:id?tab=fiber&l2=NKS02X3IJK5`: opens the OLT's tree with that L2 expanded.
  - `/devices/:id?tab=fiber&onu=0-0-0-1:22`: opens the ONU detail drawer.

---

## 4. Pages

### 4.1 `/fiber`: Fiber health overview

```
┌ Fiber health ─────────────────────────────── Run [2026-11-23 ▾]  7-day window · conf 0.90 ┐
│ ONUs scored   Bad (≤4)          Suspect L2   Suspect L1/PON   Suspect OLT   Model MAE       │
│ 3,367,255     41,717 · 1.24%    1,259        191              1             1.94 dB ⚠       │
│               ▼ 11,489 vs 11-20  ▼ 546        ▼ 151                         target 1.5      │
├──────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ Score distribution (log y)               │ Where the bad ONUs are                          │
│ ▁ ▁ ▁ ▁ ▂ ▂ ▃ ▄ ▅ █                      │ Drop / connector  ████████████████  36,647 88%  │
│ 1 2 3 4 5 6 7 8 9 10                     │ L2 segment        ██                 3,126  7%  │
│ red    orange amber   green              │ L1 / PON          █                  1,920  5%  │
│ click a bar → ONU search for that score  │ OLT               ·                     18      │
│                                          │ ONU hardware      ·                      6      │
├──────────────────────────────────────────┴─────────────────────────────────────────────────┤
│ Suspects   [ L2 segment | L1 / PON | OLT ]   Region [▾] Province [▾] Vendor [▾] 🔍   ⬇ CSV  │
│ #  L2 name        L1 name       OLT          Province     ONUs  Bad  Bad%  Peer Δ  Excess Impact│
│ 1  NKS02X3IJK5    NKS02X3023Q   NKS02007G00  นครสวรรค์      9     9   100%  −9.7 dB 11.4  112 │
│ 2  KKN05X0003E    KKN05X0003B   KKN05001G00  ขอนแก่น       14    12    86%  −6.6 dB  6.8   97 │
│ …  row click → /devices/:id?tab=fiber&l2=…                                                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
  ▸ Model & data quality (collapsed): feature importance bars, MAE trend, sentinel/null rates per vendor,
    inventory flags (8.3K no ODN row, 257K ranging mismatch) — "inventory audit" link
```

- The **KPI strip** reuses the KPI component from the device list. Each delta compares with the previous run.
- The **score histogram** uses ECharts with a log y-axis, because score 10 holds 72% of ONUs and would flatten the other bars. Clicking a bar filters the ONU search (phase 2).
- The **attribution bar** is the key story: most bad ONUs are isolated drop or connector problems, and fixing one L2 segment fixes many ONUs at once.
- The **suspects table** reuses `DataTable` with server-side sort and paging, plus the URL-synced facet filters from `DeviceListPage`. The default sort is `impact` descending. Columns per level:
  - **L2:** L2, L1, OLT, province, ONUs, bad, bad %, peer Δ, median excess, impact, p-value (in a tooltip only).
  - **L1:** L1, OLT, province, ONUs, bad, bad L2s/L2s, sibling PONs, peer Δ, excess, impact. Add a row note: *"L1 maps 1:1 to the PON port, so this may be the OLT PON optic rather than feeder fiber."*
  - **OLT:** OLT, vendor/model, province, ONUs, bad, bad PONs, excess, impact.
- Show `bad_rate_shrunk` and `p_value` in a hover tooltip ("adjusted for small groups"). They are statistical details and shouldn't take a column.

### 4.2 Device dashboard → **Fiber** tab (per OLT)

```
┌ Fiber · AYT06004GO0 ── 448 ONUs · 52 bad · 2 suspect PONs · 3 suspect L2 ────── Only bad ☑ ┐
│ ODN tree                                   │ ONUs in AYT06X35P3A  (43 · all bad)            │
│ ▾ 0-0-1-3  AYT06X35P3A   43/43 ██████ L1⚠  │ ONT  L2          Score  Rx    Exp   Excess  →  │
│     AYT06X35P4B   6/6  ██████              │ 12   AYT06X35P4B  ②    −29.6 −22.4  7.2   L1   │
│     AYT06X35P4C   5/5  ██████              │ 14   AYT06X35P4B  ②    −29.4 −22.4  7.0   L1   │
│ ▸ 0-0-1-4  AYT06X35P3B   2/31  █░░░░░      │ …                                             │
│ ▸ 0-0-1-5  AYT06X35P3C   0/28  ░░░░░░      │ row click → ONU drawer                        │
│ (bar = bad share; red outline = suspect)   │                                               │
└────────────────────────────────────────────┴───────────────────────────────────────────────┘
```

The OLT name, the ONU total (448) and the `AYT06X35P3A` row (43/43 bad, Rx −29.6, excess 7.2) come from the real run. The other counts and names in this sketch are made up.

- **Left, the ODN tree:** L1 (PON) → L2. Each node shows `bad/total`, a bad-share bar, its median Rx, and a ⚠ badge when it is on a suspect list, with the level it was attributed to. Sort by bad share. "Only bad" hides nodes with no bad ONUs, because an OLT can have more than 100 PONs.
- **Right, the ONU table** for the selected node: ONT, L2, score chip, `rx_med`, `expected_rx`, `excess_loss`, `peer_delta_l2`, BIP days, conf, `attributed_to`.
- The existing **PON ports tab** gets a small score badge per port (min score, bad count) from `/score-lookup`. That way users see fiber health even without opening the Fiber tab.

### 4.3 ONU detail drawer

Use a right-side drawer, the same pattern as the Ask AI drawer, so the tree stays visible.

```
┌ ONU SRB02010G00 0-0-0-1 : 22  (real row, run 2026-11-23) ✕ ┐
│  ③  /10   Poor        confidence 0.80 (7/7 days)            │
│  Capped: Rx below −28 dBm → max 3                           │
│                                                             │
│  Why this score                       sub-score   weight    │
│  Power      rx_med −28.4 dBm          ▓░░░░  0.20   40%     │
│  Excess     7.8 dB more loss than     ░░░░░  0.00   25%     │
│             expected for this path                          │
│  Errors     n/a: GCOM has no BIP      ─      ─      (20%    │
│             counters; weight redistributed               →0)│
│  Stability  sd 0.02 dB, slope −0.002  ▓▓▓▓▓  1.00   15%     │
│                                                             │
│  Rx: measured vs expected   (ECharts, 7–30 days)            │
│  −20.6 ┤ - - - - - - - - - expected (±1.9 dB band)          │
│  −28   ┤ ....................  sensitivity                  │
│  −28.4 ┤ ●──●──●──●──●──●──●  measured                      │
│                                                             │
│  Likely location: drop / connector (attributed_to = drop)   │
│  Peers: −7.7 dB vs its L2 siblings · −7.0 dB vs its L1      │
│  Path: 1.66 km · split 1:64 (8×4) · class unknown · GCOM    │
│  Flags: none  | hw_flag | no ODN row | topo mismatch | …    │
│  [Ask AI about this ONU]                                    │
└─────────────────────────────────────────────────────────────┘
```

- The sub-score rows map one to one to `s_power`, `s_excess`, `s_error` and `s_stability`. A missing sub-score shows as "not available (GCOM/Raisecom have no BIP counters); its weight was redistributed". This matters, because those vendors score worse partly for this reason (an open point in the ML design).
- Show the **caps**, derived from `rx_med` and `bip_days`, explicitly. Otherwise a 0.6 weighted score that displays as 3 looks like a bug.
- Draw the expected Rx with a **±MAE band** (1.9 dB), not as a single line, so users don't read `excess_loss` as more precise than it is.
- **Ask AI** opens the chat drawer pre-filled with the ONU key. The chat tool (§6) does the rest.

---

## 5. Visual conventions

| Score | Label | Colour (Tailwind) | Note |
|---|---|---|---|
| 1–3 | Poor | `red-600` | below sensitivity, or errors every day |
| 4–5 | Weak | `orange-500` | 4 is the "bad" threshold used by attribution |
| 6–7 | Fair | `amber-400` | |
| 8–10 | Good | `emerald-600` | |

- Show the score as a round chip with the number in it, never colour alone, for accessibility.
- **Low confidence** (`conf < 0.5`) shows as a hollow chip with a tooltip "based on N of 7 days". In single-day mode the confidence is about 0.11, and those scores shouldn't look as certain as 7-day ones.
- **Excess loss and peer Δ** show in dB with a sign. Bold them when they exceed 3 dB, the threshold the attribution rule uses.
- Every page shows the **run date and window** in its header, because these are daily batch results, not live data.

---

## 6. Assistant and MCP tools

Add read-only tools to the shared registry so the chat and MCP clients can use the same data:

| Tool | Input | Output |
|---|---|---|
| `fiber_overview` | `date?` | The summary from §2, trimmed |
| `list_fiber_suspects` | `level, region?, province?, vendor?, limit≤50` | Ranked suspects |
| `get_onu_fiber_score` | `device, ponport, ontid` | Full score row plus sub-score explanation |
| `fiber_device_tree` | `device` | Per-PON and per-L2 bad counts for one OLT |

Add one prompt to the system prompt: *"Scores are 1 (poor) to 10 (excellent) from a daily batch; always state the run date and confidence; L1 suspects may be OLT optics."* The existing chat `table` SSE event can then render suspect lists inline in the chat.

---

## 7. Phasing

1. **MVP:** `/api/fiber/summary` and `/suspects`, the `/fiber` page (KPIs, histogram, attribution, suspects table with CSV), and links into the device dashboard.
2. **Per-OLT view:** the tree and ONU endpoints, the Fiber tab, the ONU drawer with daily history, and score badges on the PON ports tab.
3. **Assistant:** the fiber tools in the registry, plus Ask AI from the drawer.
4. **Later:**
   - A trend view across runs (bad-ONU count per province over time; whether a suspect L2 persists across days).
   - An "inventory audit" list (range mismatch, multi-device L2, large `|excess|` with no errors).
   - Moving scores into Postgres tables once the external DDL is approved.
   - Ticket feedback for Phase-2 calibration.

## 8. Open questions

- **Who runs the pipeline in production, and where?** The backend needs read access to `ml/out` and `ml/lake`. That means the same host or a shared mount, or the run publishes a slim serving copy (score Parquet without the `dq_*`/model internals, plus the CSVs and JSON) to the app host.
- **Retention:** how many runs to keep for the run picker and the trends? Each run is about 340 MB of Parquet.
- **Access:** should fiber pages be visible to all users, or only to FTTx/NOC roles?

---

## 9. Implementation status (2026-11-25)

Phases 1, 2 and 3 are built. Phase 4 items are not started.

| Piece | Where |
|---|---|
| DuckDB reads, suspect enrichment from `device` | `backend/app/queries/fiber.py` |
| REST API: `/api/fiber/runs`, `/summary`, `/suspects` (+ `.csv`), `/devices/{id}/tree`, `/devices/{id}/onus`, `/devices/{id}/ponports`, `/devices/{id}/onu` | `backend/app/api/fiber.py` |
| Config: `ML_OUT_DIR` (default `../ml/out`), `ML_LAKE_DIR` (`../ml/lake`), `ML_DUCKDB_THREADS` (4) | `backend/app/config.py` |
| **Fiber health** nav item and `/fiber` page | `frontend/src/pages/FiberPage.tsx`, `components/Layout.tsx` |
| OLT **Fiber** tab (`/devices/:id?tab=fiber&l1=…&l2=…&onu=ponport:ontid`) | `frontend/src/components/fiber/FiberTab.tsx` |
| ONU drawer: score breakdown, caps, Rx history chart, Ask AI | `frontend/src/components/fiber/OnuDrawer.tsx` |
| Fiber column on the PON port table | `frontend/src/components/device/PonPortPanel.tsx` |
| Chat + MCP tools: `fiber_overview`, `list_fiber_suspects`, `fiber_device_tree`, `list_fiber_onus`, `get_onu_fiber_score` (with sub-score/cap explanation) | `backend/app/tools/fiber_tools.py`, registered in `app/tools/registry.py`; prompt rules in `app/chat/prompts.py` |

Notes:
- The device dashboard's summary tab is now kept in the URL (`?tab=`), so suspect rows can deep-link into it.
- The drawer copies the score weights, caps and `min_days_for_trend` from `ml/fiber/ranges.yaml`. Keep the two in sync.
- Ask AI now sends only the ONU key; the chat calls `get_onu_fiber_score` for the numbers.
- The tools copy the weights and caps from `ml/fiber/ranges.yaml` too (`fiber_tools.py`), so there are three copies to keep in sync.
- `list_fiber_onus` was added beyond the §6 list, so the chat can list the bad ONUs on one PON or L2.
- Only about 46% of suspect rows have a region in the `device` table, so the Region filter leaves out the others.
