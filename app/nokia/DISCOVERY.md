# Discovery Design

Nokia Altiplano NBI device discovery. **AC-first**: a single intent-listing call
enumerates every IBN intent, which per-domain modules partition by `intent-type`.
No Elasticsearch is used in the discovery path.

## Run

```bash
uv run python discover.py --server <IP> --password <pass> --no-verify-ssl
```

Output is written to `output/` as raw + normalized JSON per step, plus the
assembled JSONL tables and `devices.json`.

## Data flow

```
LOGIN → ac.list_intents (all intents)
          ├── AC-DEVICE  ── device-mf/device-df → config+state+boards ─► device.jsonl
          ├── UPLINK-SFP ── uplink-connection → SFP diag (AC POST) ────► intf.jsonl
          └── AC-FIBER   ── fiber (grouped by OLT prefix)
                ├── ES-ONT (5, blocked) ─────────────────────────────┐
                └── PON-SFP ── reuses AC-FIBER's fiber:fiber config ──► ponport.jsonl
                                                ASSEMBLE → MAPPER ─────► devices.json
```

## Steps

| # | Step | Module | Call | Output file | Result |
|---|---|---|---|---|---|
| 0 | Login | `client.py` | `POST /{rel}-ac/rest/auth/login` | — | Bearer token (auto-refresh) |
| 1 | List intents | `ac.py` | `GET ibn:ibn?fields=intent(target;intent-type)` | — | all intents (~5,814) in one call |
| 2 | AC-DEVICE | `ac_device.py` | per-device `GET intent={name},{device-mf\|device-df}` | `03_ac_device` | 26 OLTs: ip, hw-type, swversion, reachable, boards |
| 3 | AC-FIBER | `ac_fiber.py` | per-fiber `GET intent={fiber},fiber` | `04_ac_fiber` | 426 fibers grouped by OLT + `fiber:fiber` config |
| 4 | PON-SFP | `pon_sfp.py` | *(reuses AC-FIBER config)* | `08_pon_sfp` | moduleclass, vendorpn, model-name |
| 5 | UPLINK-SFP | `uplink_sfp.py` | `GET` uplink intent + `POST` SFP diag action | `07_uplink_sfp` | uplink ports + SFP optics |
| 6 | ASSEMBLE | `assemble.py` | local | `device.jsonl` / `intf.jsonl` / `ponport.jsonl` | 26 / 51 / 426 rows |
| 7 | MAPPER | `mapper.py` | local | `devices.json` | 26 devices, 477 interfaces |

## AC access patterns

- **List** — querying the keyed `intent` list directly 500s ("Missing key value");
  the working form is the parent container with a `fields` selector:
  `GET .../ibn:ibn?fields=intent(target;intent-type)`.
- **Detail** — the *bare* intent GET `GET .../ibn:ibn/intent={target},{type}` returns,
  in one response:
  - top-level `required-network-state`
  - `intent-specific-data/{type}:{type}` — configuration (ip-address, hardware-type, device-version, boards, …)
  - `intent-specific-data/{type}:{type}-state` — operational state (`reachable`, `actual-active-software-on-device`)
- **Action** — `POST .../intent={target},{type}/intent-specific-data/{action}` with an
  input body (e.g. `sfp-status:show-sfp-diagnostics-and-inventory`).

## Intent-type → discovery domain

| intent-type | count* | used as |
|---|---|---|
| `device-mf` | 2 | OLT (modular fiber) |
| `device-df` | 24 | OLT (disaggregated fiber) |
| `fiber` | 426 | PON ports — `target` is `{olt}-{slot}-{pon}`, grouped to OLT by prefix |
| `uplink-connection` | 26 | uplink ports — `target` == OLT name |
| `ont` | ~2,200 | (ES-ONT path, blocked) |

\* counts from testbed `10.50.238.203`; both `device-mf` and `device-df` are OLTs.

## Field sources of note

- `swversion` ← `state.actual-active-software-on-device` (e.g. `L6GQFE25.284`), not `device-version`.
- `required-network-state` ← intent top-level (raw value, e.g. `active`).
- `reachable` ← `{type}:{type}-state.reachable`.
- `olttype` is **not** derived in discovery — set to `None`, assigned downstream at the mapping stage.

## Design decisions

- **AC-only, no ES fallback** — if the controller is unavailable discovery fails
  rather than degrading. ES is retained only for the still-blocked ES-ONT path.
- **SLOT-INV merged into AC-DEVICE** — one bare GET yields config, state, and boards,
  so all 26 OLTs (including `device-df`) get board detail. The former SLOT-INV
  hardcoded `,device-mf` path 404'd on DF OLTs.
- **PON-SFP shares AC-FIBER's `fiber:fiber` config** — avoids a second GET per fiber.
- **Cost** — ~1 list call + 1 GET per device + 1 GET per fiber (~450 calls) vs ES's
  few bulk queries. The fiber GETs dominate runtime (~2 min on the testbed).

## Blocked / not wired

- **ES-ONT** (item 5) — per-fiber ONT counts; ES path retained but not called.
- **AC-ONT** (item 9, `ac_ont.py`) and **RC-INTF / RC-INTF-ONE** (items 9–10) —
  depend on Nokia RC-Proxy, not deployed on the testbed.
