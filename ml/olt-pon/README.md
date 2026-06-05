## FTTx ML

End-to-end prototype: synthetic FTTx telemetry → ML detectors →
Streamlit dashboard.

### What's in here

| File | Purpose |
| --- | --- |
| `generate_data.py` | Builds a realistic OLT→PON→L1→L2→ONU topology and emits a week of hourly telemetry with planted anomalies. |
| `models.py`        | Three detectors: RxPower drift (IsolationForest + z-score), optical-budget regression (LinearRegression), cable bending (change-point + up/down asymmetry). |
| `app.py`           | Multi-tab Streamlit dashboard. |
| `requirements.txt` | Python deps. |
| `data/`            | Generated CSVs (telemetry, topology, ground truth). |

### Quick start (uv — recommended)

[uv](https://docs.astral.sh/uv/) handles the virtualenv and dependency
install in one step using `pyproject.toml`:

```bash
uv sync                              # creates .venv/ and installs deps
uv run python generate_data.py data  # ~86k rows, a few seconds
uv run streamlit run app.py          # opens dashboard at localhost:8501
```

If you don't have uv yet:
- macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `irm https://astral.sh/uv/install.ps1 | iex`

Common uv chores:
```bash
uv add lightgbm                      # add a new dependency
uv add --dev pytest                  # add a dev-only dep
uv lock --upgrade                    # bump versions in uv.lock
uv run python -c "import models"     # run any command in the venv
```

### Quick start (plain pip — alternative)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python generate_data.py data
streamlit run app.py
```

### ML approaches in v1

1. **RxPower drift** — per-ONU rolling features (mean, std, drop, range,
   BIP) fed into IsolationForest; combined with a fleet z-score on
   first-vs-last RxPower so slow degradation surfaces even when the
   pattern looks normal moment-to-moment.

2. **Optical budget validation** — fit `LinearRegression` on
   `(distance_km, vendor, moduleclass) → observed downstream loss`
   across the fleet. Residuals >±2.5 dB flag mis-cabling, wrong-model
   SFPs, or bad splices. Because the model fits *your* plant, it
   adapts without needing hard-coded budget tables.

3. **Cable bending** — lightweight binary change-point on RxPower per
   ONU, then confirm with downstream-vs-upstream loss asymmetry.
   Macrobend loss is wavelength-dependent (1490 nm down loses more than
   1310 nm up), so a positive `down_step − up_step` is the discriminating
   feature against e.g. transient noise or laser drift.

### Ideas for v2

- **Predictive ONU failure** — train an XGBoost/LightGBM survival model
  on temp + bias + voltage + BIP trajectories.
- **Traffic forecasting** — per-PON-port Prophet or LSTM for capacity
  planning.
- **Root-cause clustering** — when many ONUs under the same L1/L2
  splitter degrade together, attribute the fault to the splitter rather
  than the children.
- **Composite health → ticketing** — auto-open tickets when an ONU's
  composite score stays above 0.6 for >24 h.

### DataSource (schema)

Data table with following columns:
- OLT device name
- vendor
- model
- sitename
- ponport (OLT PON Port toward ONT, sample: 1-2-3-4)
- moduleclass (OLT ponport module class)
- l1_splitter (passive device, level1 splitter name)
- l2_splitter (passive device, level2 splitter name)
- ontid (ONT ID)
- device_serial (ONU device serial)
- circuit_id
- pon_txpwr (TxPower reported by OLT ponport)
- pon_rxpwr (RxPower reported by OLT ponport)
- pon_temp (Temperature reported by OLT ponport)
- olt_bias_current
- olt_voltage
- olt_in_octets (in octets reported by OLT ponport)
- olt_out_octets (out octets reported by OLT ponport)
- olt_biperr (bip error reported by OLT ponport)
- ranging (range from OLT ponport to ONU, unit is meter, reported by OLT)
- onu_tx_power
- onu_rx_power
- onu_bias_current
- onu_voltage
- onu_in_biperr
- onu_out_biperr
