# Design: Go SNMP Reboot Poller (`true-pms-online`)

## Context

The project needs a Go daemon that polls ~25,000 SNMP-enabled network devices every 15 minutes and emits reboot events. The primary design challenge is correctness: distinguishing a genuine reboot from a 32-bit counter rollover (~497-day cycle) or a stuck-MAX firmware bug, while sustaining 25,000 concurrent UDP polls within a 15-minute window. No code exists yet — this is a greenfield implementation.

---

## Deployment Model

**Short-lived process invoked by system cron every 15 minutes.** The binary starts, loads devices, polls all 25k devices concurrently, writes state to LevelDB, then exits. System cron handles the interval — no internal scheduler needed.

```
# /etc/cron.d/pms-poller
*/15 * * * * root /usr/local/bin/pms-poller --config /etc/pms-poller/config.yaml
```

A **PID lock file** (`/var/run/pms-poller.lock`) prevents overlapping runs. The file stores the running process's PID. On startup: if the file exists and the PID is still alive → exit immediately. If the file exists but the PID is dead (stale lock from crash) → overwrite and continue. On exit: delete the lock file.

---

## Directory Layout

```
true-pms-online/
├── cmd/poller/main.go               # Entry point: load config, load devices, run poll cycle, exit
├── internal/
│   ├── config/config.go             # PollerConfig struct + Viper loader
│   ├── device/
│   │   ├── model.go                 # Device, SNMPAuth structs
│   │   ├── repository.go            # DeviceRepository interface + composite loader
│   │   ├── postgres.go              # pgx implementation
│   │   └── filecache.go             # JSON file persistence + fallback
│   ├── state/
│   │   ├── model.go                 # DeviceState struct
│   │   ├── store.go                 # StateStore interface
│   │   └── leveldb.go               # LevelDB implementation
│   ├── snmp/
│   │   ├── client.go                # SNMPClient interface + gosnmp wrapper
│   │   └── oid.go                   # OID constants
│   ├── poller/
│   │   ├── uptime.go                # DetectReboot — pure function, all edge cases
│   │   ├── worker.go                # Worker pool (goroutines + channels)
│   │   └── poller.go                # RunPollCycle — wires pool, state, emitter
│   ├── event/
│   │   ├── model.go                 # RebootEvent, PollRecord structs
│   │   ├── emitter.go               # EventEmitter interface + MultiEmitter
│   │   ├── logger.go                # slog structured-log implementation (stderr/stdout)
│   │   ├── rebootlog.go             # reboot event → daily-rotated JSON file
│   │   ├── postgres.go              # reboot event → Postgres INSERT + retry queue drain
│   │   ├── retryqueue.go            # file-based pending queue (NDJSON) for failed inserts
│   │   ├── polllog.go               # poll result per device → daily-rotated JSON file
│   │   └── uptimeupsert.go          # batch upsert poll results → device_last_uptime
│   └── metrics/
│       └── pushgateway.go           # Prometheus Pushgateway client (optional)
├── config.yaml
├── go.mod / go.sum
├── AGENTS.md
└── CLAUDE.md
```

---

## Key Structs

### `Device` (internal/device/model.go)
```go
// Device is a flat struct — all fields map directly to columns in the device table.
// v3-specific fields (SecurityName…PrivKey) are empty string for v2c devices.
type Device struct {
    IP            string
    Name          string
    Port          uint16 // default 161
    SNMPVersion   int    // 2 (v2c) or 3 (v3)
    Community     string // v2c only
    SecurityName  string // v3: USM username
    SecurityLevel string // v3: "noAuthNoPriv" | "authNoPriv" | "authPriv"
    AuthProtocol  string // v3: "MD5" | "SHA" | "SHA256"
    AuthKey       string // v3
    PrivProtocol  string // v3: "DES" | "AES" | "AES256"
    PrivKey       string // v3
}
```

### `DeviceState` (internal/state/model.go)
```go
type DeviceState struct {
    // Probe result (persisted; re-probe triggered if ReprobeAt is reached)
    EngineProbed    bool
    UseEngineOIDs   bool
    ReprobeAt       time.Time  // zero = never re-probe; set to future time to force re-probe (e.g. after firmware upgrade window)

    // Path A — snmpEngineBoots/snmpEngineTime
    LastEngineBoots uint32
    LastEngineTime  uint32     // seconds

    // Path B — sysUptime fallback
    LastSysUptime   uint32
    LastWallClock   time.Time
    MaxValueStreak  int        // consecutive 0xFFFFFFFF hits; reset to 0 on any non-MAX value
    LastBootTime    time.Time  // estimated boot time; updated on every detected reboot

    // Shared
    ConsecutiveFailures int    // SNMP errors in a row; reset to 0 on success; alert when >= max_consecutive_failures
}
```

### `RebootEvent` + `PollRecord` (internal/event/model.go)
```go
// DetectionMethod indicates which algorithm was used to determine a reboot.
type DetectionMethod string

const (
    MethodEngineBoots DetectionMethod = "engine_boots"  // Path A: snmpEngineBoots incremented
    MethodSysUptime   DetectionMethod = "sys_uptime"    // Path B: sysUptime went backwards
    MethodGapInferred DetectionMethod = "gap_inferred"  // Path B: inferred from poller outage gap
)

type RebootEvent struct {
    DeviceIP        string
    DeviceName      string
    EstimatedBoot   time.Time
    DetectedAt      time.Time
    // PrevValue/CurrValue semantics depend on DetectionMethod:
    //   engine_boots → snmpEngineBoots values
    //   sys_uptime / gap_inferred → sysUptime timetick values
    PrevValue       uint32
    CurrValue       uint32
    IsSuspected     bool            // true only when DetectionMethod == MethodGapInferred
    DetectionMethod DetectionMethod
}

// PollRecord is written to the JSON log file for every device polled.
type PollRecord struct {
    Timestamp       time.Time        `json:"timestamp"`
    IP              string           `json:"ip"`
    Name            string           `json:"name"`
    SysUptime       *uint32          `json:"sys_uptime,omitempty"`    // nil for Path A devices
    EngineBoots     *uint32          `json:"engine_boots,omitempty"`  // nil for Path B devices
    EngineTime      *uint32          `json:"engine_time,omitempty"`   // nil for Path B devices
    Error           string           `json:"error,omitempty"`
    IsReboot        bool             `json:"is_reboot"`
    IsSuspected     bool             `json:"is_suspected,omitempty"`
    DetectionMethod DetectionMethod  `json:"detection_method,omitempty"` // only set when is_reboot=true
    BootTime        *time.Time       `json:"boot_time,omitempty"`     // nil when no reboot
}
```

### Poll log (`poll_log_file`) — one record per device per run, NDJSON, daily rotation:
```json
{"timestamp":"2025-05-27T10:00:01Z","ip":"10.0.0.1","name":"HW-SW-01","sys_uptime":123456,"is_reboot":false}
{"timestamp":"2025-05-27T10:00:02Z","ip":"10.0.0.2","name":"ZTE-OLT-03","sys_uptime":500,"is_reboot":true,"boot_time":"2025-05-27T09:58:47Z"}
{"timestamp":"2025-05-27T10:00:03Z","ip":"10.0.0.3","name":"FH-ONU-07","error":"snmp timeout","is_reboot":false}
```

### Reboot event log (`reboot_log_file`) — one record per reboot event only, NDJSON, daily rotation:
```json
{"timestamp":"2025-05-27T10:00:02Z","ip":"10.0.0.2","name":"ZTE-OLT-03","boot_time":"2025-05-27T09:58:47Z","is_suspected":false,"detection_method":"engine_boots","prev_uptime":9876543,"curr_uptime":500}
{"timestamp":"2025-05-27T10:00:05Z","ip":"10.0.0.7","name":"FH-ONU-22","boot_time":"2025-05-27T09:59:10Z","is_suspected":false,"detection_method":"sys_uptime","prev_uptime":8765432,"curr_uptime":300}
{"timestamp":"2025-05-27T10:15:07Z","ip":"10.0.1.5","name":"HW-OLT-12","boot_time":"2025-05-27T10:10:00Z","is_suspected":true,"detection_method":"gap_inferred","prev_uptime":1234567,"curr_uptime":30000}
```

**Daily log rotation (in-process):** Both log files are named with the current date suffix (`poll.2025-05-27.log`, `reboot.2025-05-27.log`). On each open, the writer checks today's date; if the date has rolled over since the file was last opened, it closes the old file and opens a new one. No external `logrotate` dependency.

**Log retention (in-process):** At the start of each run, after opening the log files, the binary scans the log directory and deletes any `poll.*.log` and `reboot.*.log` files whose date suffix is older than `log_retention_days` (default: 30). Deletion errors are logged as warnings and do not abort the run.

---

## Core Interfaces

```go
// internal/state/store.go
type StateStore interface {
    Get(ip string) (DeviceState, error)
    Put(ip string, state DeviceState) error
    Delete(ip string) error
    Close() error
}

// internal/device/repository.go
type DeviceRepository interface {
    LoadFromDB(ctx context.Context) ([]Device, error)
    LoadFromCache() ([]Device, error)
    SaveCache(devices []Device) error
}

// internal/event/emitter.go
// MultiEmitter fans out to all configured emitters (reboot log file + optional Postgres).
type EventEmitter interface {
    Emit(ctx context.Context, event RebootEvent) error
    Close() error
}

// internal/event/polllog.go
type PollLogger interface {
    Write(record PollRecord) error  // goroutine-safe; rotates file on date change
    Close() error
}

// internal/event/rebootlog.go  — implements EventEmitter
// Writes reboot events to a daily-rotated NDJSON file.

// internal/event/postgres.go   — implements EventEmitter (optional)
// Inserts reboot events into a Postgres table.

// internal/snmp/client.go
// Supports SNMPv2c and SNMPv3. Version and auth params come from Device.Auth.
type SNMPClient interface {
    // Get fetches multiple OIDs in a single GET PDU. Returns map of OID → uint32 value.
    Get(ctx context.Context, device Device, oids []string) (map[string]uint32, error)
}
```

---

## OIDs Used

All devices are SNMPv2c. Engine OIDs are probed once per device on first poll — used if supported, permanently skipped if not.

| OID | Name | Used when |
|---|---|---|
| `1.3.6.1.6.3.10.2.1.2.0` | `snmpEngineBoots` | Device supports it (probed once) |
| `1.3.6.1.6.3.10.2.1.3.0` | `snmpEngineTime` | Device supports it (probed once) |
| `1.3.6.1.2.1.1.3.0` | `sysUptime` | Fallback when engine OIDs unavailable |

---

## Reboot-Detection Algorithm (`internal/poller/uptime.go`)

Pure function — no I/O, fully unit-testable. Two paths depending on what the device supports.

### Path selection — probe once, remember result

**Probe GET (first poll only) — all 3 OIDs in a single PDU:**
```
GET [snmpEngineBoots, snmpEngineTime, sysUptime]
    ["1.3.6.1.6.3.10.2.1.2.0", "1.3.6.1.6.3.10.2.1.3.0", "1.3.6.1.2.1.1.3.0"]
```
One UDP round-trip. The response varbinds determine the path:
- Both engine OIDs return valid integers → `UseEngineOIDs = true`; `sysUptime` value from the same response is discarded
- Either engine OID returns `noSuchObject` / error → `UseEngineOIDs = false`; use the `sysUptime` value from the same response to seed Path B state immediately

`EngineProbed = true` is written to LevelDB — probe never repeats for this device.

**Regular polls (after probe) — minimal varbinds per path:**
```
Path A:  GET [snmpEngineBoots, snmpEngineTime]   — 2 OIDs, 1 request
Path B:  GET [sysUptime]                         — 1 OID,  1 request
```

`gosnmp` supports multi-varbind GET natively: `snmp.Get([]string{oid1, oid2, ...})`.

On subsequent polls:
  IF DeviceState.UseEngineOIDs: use Path A
  ELSE:                         use Path B

---

### Path A — snmpEngineBoots + snmpEngineTime (preferred)

```
DetectRebootEngine(prev DeviceState, boots uint32, engineTime uint32, now time.Time)

IF boots > prev.LastEngineBoots:
    → reboot confirmed (boots_delta = boots - prev.LastEngineBoots)
    → estimatedBoot = now - duration(engineTime seconds)
    → update LastBootTime in state
    → return isReboot=true, method=engine_boots

IF boots == 0 AND prev.LastEngineBoots == 0xFFFFFFFF:
    → snmpEngineBoots wrapped (2^32 reboots) — treat as reboot
    → estimatedBoot = now - duration(engineTime seconds)
    → return isReboot=true, method=engine_boots

IF boots == prev.LastEngineBoots AND engineTime < prev.LastEngineTime:
    → engineTime went backwards within same boots value — firmware anomaly
    → treat as reboot
    → estimatedBoot = now - duration(engineTime seconds)
    → return isReboot=true, method=engine_boots

IF boots < prev.LastEngineBoots AND NOT wrap-case above:
    → boots decreased unexpectedly (device reset its own counter, or firmware bug)
    → log warning, treat as reboot conservatively
    → return isReboot=true, method=engine_boots

ELSE:
    → normal, return isReboot=false
```

**Firmware downgrade / OID disappears:** If `UseEngineOIDs=true` but a subsequent poll returns `noSuchObject` for engine OIDs (e.g. firmware downgrade), the poller detects this, logs a warning, sets `UseEngineOIDs=false`, clears engine state, and switches to Path B immediately. `EngineProbed` remains `true` but `UseEngineOIDs` flips — no re-probe penalty.

No rollover ambiguity, no stuck-MAX handling needed. `snmpEngineTime` overflows after ~136 years.

---

### Path B — sysUptime fallback (devices that don't support engine OIDs)

```
DetectRebootUptime(prev DeviceState, current uint32, now time.Time)

// 2^32 timeticks / 100 = 42,949,672 seconds = ~497.1 days
// Use 99% of that as rollover threshold to absorb clock drift and missed polls
ROLLOVER_THRESHOLD = 42,520,176 seconds  (~492 days = 99% of 32-bit timetick period)
MAX_UPTIME         = 0xFFFFFFFF

// Note: all arithmetic on uptime values uses int64 to correctly detect negative deltas.
// uint32 subtraction in Go wraps silently; always cast to int64 first.

1. Stuck-MAX firmware bug (current == MAX_UPTIME):
   → increment MaxValueStreak
   → if streak >= MaxValueStreakMax (default 3): suppress, preserve state, return isReboot=false
   → else: fall through (allow single-cycle evaluation; streak accumulates)

2. Non-MAX value: reset MaxValueStreak = 0

3. delta = int64(current) - int64(prev.LastSysUptime)   // must use int64
   wallElapsed = now.Sub(prev.LastWallClock).Seconds()
   if wallElapsed < 0: wallElapsed = 0                   // NTP jump backward guard

4a. delta < 0 AND wallElapsed >= ROLLOVER_THRESHOLD:
    → 32-bit counter rollover — update state, return isReboot=false

4b. delta < 0 AND wallElapsed < ROLLOVER_THRESHOLD:
    → genuine reboot
    → estimatedBoot = now - duration(current / 100.0 seconds)
    → update LastBootTime in state
    → return isReboot=true, method=sys_uptime

4c. delta >= 0:
    deltaSeconds = float64(delta) / 100.0
    gap = wallElapsed - deltaSeconds       // wall time not accounted for by uptime growth
    IF gap > GAP_REBOOT_THRESHOLD (default 1800s):
        → reboot occurred during poller outage
        → estimatedBoot = now - duration(current / 100.0 seconds)
        → update LastBootTime in state
        → return isReboot=true, isSuspected=true, method=gap_inferred
    ELSE:
        → normal — return isReboot=false
```

> `isSuspected=true` only applies to **Path B (sysUptime) devices** — it means the reboot was inferred from a poller gap, not directly observed. Path A devices (`snmpEngineBoots`) never set `isSuspected=true` because the boots counter persists on the device regardless of how long the poller was offline — a boots increment is always a certain reboot.

---

**Full edge case matrix:**

| Scenario | Path | Result |
|---|---|---|
| First poll, engine OIDs supported | A | Probe succeeds, seed state |
| First poll, engine OIDs not supported | B | Probe fails, fall back, seed state |
| Normal operation | A or B | No event |
| Device rebooted | A | Certain reboot (`boots` incremented) |
| Device rebooted multiple times between polls | A | Certain reboot, `boots_delta` shows count |
| 32-bit sysUptime rollover (~497 days) | B | No event (wall elapsed ≥ threshold) |
| Stuck MAX sysUptime (firmware bug) | B | Suppressed after streak ≥ 3 |
| Poller down N hours, Path A device rebooted | A | Certain reboot — `boots` incremented, no gap ambiguity |
| Poller down N hours, Path B device rebooted mid-gap | B | Suspected reboot (`isSuspected=true`) — sysUptime limitation |
| Poller down N hours, Path B device rebooted near end | B | Certain reboot |
| NTP clock jump backward | B | wallElapsed treated as 0, suppress gap check |
| SNMP timeout / error | A or B | Preserve old state, no event |

---

## Worker Pool (`internal/poller/worker.go`)

- **500 workers** (default) — handles 25,000 devices with ~5s SNMP timeout in ~14 minutes, leaving 1-minute margin
- Per-device context with hard `SNMPTimeout` deadline
- Channels: `jobCh chan PollJob` (buffered) → workers → `resultCh chan PollResult` (buffered)
- Main goroutine enqueues all jobs, then collects results, writes LevelDB, emits events
- Cycle-overlap guard: atomic flag or `sync.Mutex`; if a cycle is still running when cron fires, log a warning and skip

```
14-minute hard deadline on top-level context:
ctx, cancel := context.WithTimeout(ctx, 14*time.Minute)
```

---

## Device List Loading

```sql
SELECT ip, name, port,
       snmp_version, community,
       security_name, security_level,
       auth_protocol, auth_key,
       priv_protocol, priv_key
FROM device
```

Columns for v3 fields (`security_name`, `security_level`, `auth_protocol`, `auth_key`, `priv_protocol`, `priv_key`) are `NULL` for v2c devices and ignored during mapping. `port` defaults to 161 when NULL.

**Expected `device` table columns (DDL not managed by the binary):**
```sql
ALTER TABLE device ADD COLUMN IF NOT EXISTS port          SMALLINT     DEFAULT 161;
ALTER TABLE device ADD COLUMN IF NOT EXISTS snmp_version  SMALLINT     NOT NULL DEFAULT 2;
ALTER TABLE device ADD COLUMN IF NOT EXISTS community     VARCHAR(128);
ALTER TABLE device ADD COLUMN IF NOT EXISTS security_name VARCHAR(128);
ALTER TABLE device ADD COLUMN IF NOT EXISTS security_level VARCHAR(32);
ALTER TABLE device ADD COLUMN IF NOT EXISTS auth_protocol VARCHAR(16);
ALTER TABLE device ADD COLUMN IF NOT EXISTS auth_key      TEXT;
ALTER TABLE device ADD COLUMN IF NOT EXISTS priv_protocol VARCHAR(16);
ALTER TABLE device ADD COLUMN IF NOT EXISTS priv_key      TEXT;
```

Every invocation (each cron run):
1. Try PostgreSQL (10s timeout) → on success, save cache file → use DB result
2. On DB failure → load from cache file → log warning
3. If no cache exists → fatal exit (nothing to poll)
- **Pruning**: compare new list against LevelDB keys; delete state for removed IPs (configurable via `prune_removed_devices`)
- All SNMP auth parameters are per-device from DB; no global community default needed

---

## Libraries

| Concern | Library |
|---|---|
| SNMP | `github.com/gosnmp/gosnmp` (pure Go, no CGo, supports v1/v2c/v3) |
| LevelDB | `github.com/syndtr/goleveldb/leveldb` |
| PostgreSQL | `github.com/jackc/pgx/v5` |
| Config | `github.com/spf13/viper` |
| Logging | `log/slog` (stdlib, Go 1.21+) |
| Metrics (optional) | `github.com/prometheus/client_golang/prometheus` + `promutil/push` |

No cron library needed — scheduling is handled by the OS.

> **Why Pushgateway, not a scrape endpoint?** Short-lived processes exit after each run, so Prometheus cannot scrape them. The binary pushes a metric snapshot to a Pushgateway at the end of each cycle; Prometheus then scrapes the Pushgateway.

**No CGo libraries** — required for `GOOS=linux GOARCH=386` cross-compilation.

---

## Configuration (`config.yaml` + `POLLER_*` env vars)

```yaml
# Worker pool
concurrency: 500                      # number of concurrent SNMP workers
snmp_timeout: 5s                      # per-device timeout (max wall time = snmp_timeout * (snmp_retries+1))
snmp_retries: 1                       # additional attempts after the first (total attempts = snmp_retries + 1)

# Process
lock_file: "/var/run/pms-poller.lock"

# Persistence
leveldb_path: "./data/state.db"
device_cache_file: "./data/devices.json"

# Logging
poll_log_dir: "./logs"
reboot_log_dir: "./logs"
log_retention_days: 30                # 0 = keep forever
log_level: "info"                     # debug | info | warn | error

# PostgreSQL (shared connection pool for device list + event writes)
postgres_dsn: ""                      # set via POLLER_POSTGRES_DSN env var
postgres_timeout: 10s

# Reboot event → Postgres (optional)
reboot_pg_table: ""                   # e.g. "device_reboot_event"; disabled if empty
reboot_pg_timeout: 3s
pg_retry_queue_file: "./data/pg_retry.queue"

# Live uptime upsert → Postgres (optional)
uptime_pg_table: "device_last_uptime" # disabled if empty
uptime_batch_size: 500
pg_uptime_retry_queue_file: "./data/pg_uptime_retry.queue"

# Detection thresholds
rollover_threshold_seconds: 42520176  # 99% of 32-bit timetick period (~492 days)
max_value_streak_threshold: 3         # suppress reboot after N consecutive 0xFFFFFFFF hits
max_consecutive_failures: 10          # log alert after N consecutive SNMP failures per device
gap_reboot_threshold_seconds: 1800    # min gap (wall - uptime_delta) to infer gap reboot

# Device management
prune_removed_devices: true

# SNMP (v2c and v3 supported; all auth params loaded per-device from DB)
default_port: 161

# Prometheus Pushgateway (optional)
pushgateway_url: ""                   # e.g. "http://pushgateway:9091"; disabled if empty
pushgateway_job: "pms_poller"

```

---

## Live Uptime Table (`device_last_uptime`)

After each poll cycle completes, upsert every successfully polled device into `device_last_uptime`. One row per IP — always reflects the latest known state.

**Table schema:**
```sql
CREATE TABLE device_last_uptime (
    ip              VARCHAR(45)  PRIMARY KEY,
    name            TEXT         NOT NULL,
    sys_uptime      BIGINT,                    -- NULL for Path A devices
    engine_boots    BIGINT,                    -- NULL for Path B devices
    engine_time     BIGINT,                    -- NULL for Path B devices
    polled_at       TIMESTAMPTZ  NOT NULL,
    poll_method     VARCHAR(32)  NOT NULL,     -- 'engine_oids' | 'sys_uptime'
    last_reboot_at  TIMESTAMPTZ               -- last estimated boot time; NULL if never detected
);
```

**Upsert statement (runs once per successfully polled device):**
```sql
INSERT INTO device_last_uptime (ip, name, sys_uptime, engine_boots, engine_time, polled_at, poll_method, last_reboot_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (ip) DO UPDATE SET
    name           = EXCLUDED.name,
    sys_uptime     = EXCLUDED.sys_uptime,
    engine_boots   = EXCLUDED.engine_boots,
    engine_time    = EXCLUDED.engine_time,
    polled_at      = EXCLUDED.polled_at,
    poll_method    = EXCLUDED.poll_method,
    last_reboot_at = EXCLUDED.last_reboot_at;
```

**Batching:** Rather than one upsert per device (25,000 round-trips), results are collected and sent in batches of configurable size (default 500 rows) using `pgx` batch API (`pgx.Batch`). This reduces the upsert phase to ~50 round-trips for 25,000 devices.

**Failure handling:** Same retry queue pattern as reboot events — failed batches are queued to `pg_uptime_retry.queue` and retried on the next run. Devices that errored during SNMP polling are skipped (no upsert for that cycle — `polled_at` stays at last known value).

**Config additions:**
```yaml
uptime_pg_table: "device_last_uptime"   # empty = disabled
uptime_batch_size: 500
pg_uptime_retry_queue_file: "./data/pg_uptime_retry.queue"
```

---

## Reboot Event Outputs

### 1. Reboot log file (`internal/event/rebootlog.go`)

Implements `EventEmitter`. Appends one JSON line per reboot event to a daily-rotated file.

**File naming:** `<reboot_log_dir>/reboot.2025-05-27.log` — date is derived from `event.DetectedAt` UTC. The writer holds the current file handle + open date; on `Emit`, if `today != openDate`, it closes the current file and opens a new one (thread-safe via `sync.Mutex`).

### 2. Postgres insert with retry queue (`internal/event/postgres.go`) — optional

Implements `EventEmitter`. Reuses the existing pgx connection pool. Disabled if `reboot_pg_table` is empty.

**Table schema (create once, not managed by the binary):**
```sql
CREATE TABLE device_reboot_event (
    id               BIGSERIAL PRIMARY KEY,
    detected_at      TIMESTAMPTZ  NOT NULL,
    ip               VARCHAR(45)  NOT NULL,
    name             TEXT         NOT NULL,
    boot_time        TIMESTAMPTZ,
    is_suspected     BOOLEAN      NOT NULL DEFAULT FALSE,
    detection_method VARCHAR(32)  NOT NULL,  -- 'engine_boots' | 'sys_uptime' | 'gap_inferred'
    prev_value       BIGINT,                  -- snmpEngineBoots or sysUptime timeticks
    curr_value       BIGINT
);

CREATE INDEX ON device_reboot_event (ip, detected_at);
```

**Retry queue flow (`internal/event/retryqueue.go`):**

```
Each cron run:

STEP 1 — Drain pending queue (before poll cycle):
  Read pg_retry_queue_file (NDJSON, one RebootEvent per line)
  For each queued event:
    Attempt INSERT (short timeout)
    On success: mark for removal
    On failure: keep in queue, stop draining (DB still down)
  Rewrite queue file with only the failed entries

STEP 2 — Poll cycle runs normally

STEP 3 — On new reboot event detected:
  Attempt INSERT
  On success: done
  On failure: append event to pg_retry_queue_file
              log warning "insert failed, queued for retry"
```

The queue file is plain NDJSON (`pg_retry.queue`), always appended atomically per event. It is human-readable and can be manually replayed or cleared by an operator. No TTL on queued events — they retry on every run until they succeed or are manually removed.

### Fan-out via `MultiEmitter`

`main.go` builds a `MultiEmitter` from whichever emitters are configured:

```go
emitters := []EventEmitter{rebootLogEmitter}        // always present
if cfg.RebootPGTable != "" {
    emitters = append(emitters, pgEmitter)
}
emitter := NewMultiEmitter(emitters...)
```

---

## Prometheus Metrics (`internal/metrics/pushgateway.go`)

At the end of each poll cycle, if `pushgateway_url` is set, push a snapshot using `prometheus/client_golang/prometheus/push`:

| Metric | Type | Labels | Description |
|---|---|---|---|
| `pms_poll_devices_total` | Gauge | — | Total devices polled this cycle |
| `pms_poll_success_total` | Gauge | — | Devices that responded successfully |
| `pms_poll_error_total` | Gauge | — | Devices that timed out or returned an error |
| `pms_poll_reboot_total` | Gauge | — | Reboot events detected this cycle |
| `pms_poll_cycle_duration_seconds` | Gauge | — | Wall-clock time for the full cycle |
| `pms_poll_last_run_timestamp` | Gauge | — | Unix timestamp of cycle completion (useful for alerting on missed runs) |

```go
// internal/metrics/pushgateway.go
type CycleMetrics struct {
    DevicesTotal  int
    SuccessTotal  int
    ErrorTotal    int
    RebootTotal   int
    DurationSecs  float64
}

func Push(url, job string, m CycleMetrics) error {
    // register gauges, set values, push to gateway
    // returns nil if url is empty (feature disabled)
}
```

`Push` is called once in `main.go` after `RunPollCycle` returns. If the push fails, log a warning but do not fail the overall run — metrics are best-effort.

---

## Additional Error Scenarios

Beyond the spec:
- **SNMP auth failure / bad community** — log warn, preserve state, count metric
- **noSuchObject PDU** — treat as unreachable for this cycle
- **Persistent unreachability** — track `ConsecutiveFailures` in `DeviceState`; alert after configurable threshold
- **LevelDB write failure** — log error, continue; next cycle may emit a duplicate event (acceptable trade-off); downstream deduplication key: `(DeviceIP, EstimatedBoot)`
- **NTP clock jump forward > ROLLOVER_THRESHOLD** — log warning, treat poll as inconclusive, preserve old state
- **Process restart mid-cycle** — unprocessed devices re-polled next cycle; no data loss
- **SIGTERM/SIGINT** — stop cron, cancel cycle context (with grace period), flush LevelDB, exit cleanly
- **64-bit uptime OID** — `Device.UptimeOID` field allows per-vendor override if vendor uses non-standard uptime MIB

---

## Implementation Sequence

1. `go.mod` + directory scaffold
2. `internal/config` — load, validate
3. `internal/state/leveldb.go` — StateStore + JSON serialization
4. `internal/device/filecache.go` — JSON device cache
5. **`internal/poller/uptime.go`** — DetectReboot pure function + table-driven tests
6. `internal/device/postgres.go` + `repository.go` — DB load + fallback
7. `internal/snmp/client.go` — gosnmp wrapper
8. `internal/poller/worker.go` + `poller.go` — worker pool + RunPollCycle
9. `internal/event/rebootlog.go` — daily-rotated reboot event file
10. `internal/event/retryqueue.go` — NDJSON retry queue read/write/drain
11. `internal/event/postgres.go` — Postgres INSERT emitter + queue drain on startup
12. `internal/event/polllog.go` — daily-rotated poll log file
13. `cmd/poller/main.go` — lock file, drain queue, load devices, run cycle, push metrics, exit
14. `internal/metrics/pushgateway.go` — Prometheus push (optional, no-op if URL empty)

---

## Test Cases

All unit tests use table-driven style (`[]struct{ name, input, expected }`). No real SNMP, Postgres, or LevelDB in unit tests — use interfaces and mocks.

---

### `internal/poller/uptime_test.go` — DetectRebootEngine (Path A)

| # | Test name | Input | Expected |
|---|---|---|---|
| 1 | First poll | `EngineProbed=false` | `isReboot=false`, state seeded |
| 2 | Normal increment | `boots=5→5, engineTime=100→200` | `isReboot=false` |
| 3 | Single reboot | `boots=5→6, engineTime=7200→300` | `isReboot=true, method=engine_boots` |
| 4 | Multiple reboots between polls | `boots=5→8` | `isReboot=true, method=engine_boots` |
| 5 | engineTime backwards, same boots | `boots=5→5, engineTime=500→100` | `isReboot=true, method=engine_boots` |
| 6 | boots and engineTime both zero | `boots=0→0, engineTime=0→0` | `isReboot=false` (fresh device, same state) |

---

### `internal/poller/uptime_test.go` — DetectRebootUptime (Path B)

| # | Test name | Input | Expected |
|---|---|---|---|
| 7 | First poll | `LastWallClock=zero` | `isReboot=false`, state seeded |
| 8 | Normal increment | `prev=1000, curr=2000, elapsed=10s` | `isReboot=false` |
| 9 | Direct reboot (uptime backwards) | `prev=9000000, curr=500, elapsed=600s` | `isReboot=true, method=sys_uptime` |
| 10 | sysUptime = 0 on fresh boot | `prev=5000000, curr=0, elapsed=600s` | `isReboot=true, method=sys_uptime` |
| 11 | 32-bit rollover | `prev=4294900000, curr=100000, elapsed=43000000s` | `isReboot=false` |
| 12 | Rollover threshold not reached | `prev=4294900000, curr=100000, elapsed=30000000s` | `isReboot=true` (treated as reboot) |
| 13 | Stuck MAX, first hit (streak=1) | `curr=0xFFFFFFFF, streak=0` | `isReboot=false`, `streak=1` |
| 14 | Stuck MAX, second hit (streak=2) | `curr=0xFFFFFFFF, streak=1` | `isReboot=false`, `streak=2` |
| 15 | Stuck MAX, suppressed (streak=3) | `curr=0xFFFFFFFF, streak=3` | `isReboot=false`, `streak=4` |
| 16 | Stuck MAX recovery | `prev=0xFFFFFFFF streak=3, curr=500` | `streak reset=0`, evaluate normally |
| 17 | Gap reboot (poller outage) | `prev=10000, curr=20000, elapsed=7200s, deltaSeconds=100s` | `isReboot=true, method=gap_inferred, isSuspected=true` |
| 18 | Large elapsed but gap within threshold | `elapsed=2000s, deltaSeconds=1900s, gap=100s` | `isReboot=false` (gap < 1800s threshold) |
| 19 | Gap exactly at threshold | `gap=1800s` | `isReboot=true` (boundary, threshold inclusive) |
| 20 | NTP clock jump backward | `wallElapsed<0` | treat as 0, no gap check, no rollover |
| 21 | Delta = 0 (same tick value) | `prev=curr=5000, elapsed=900s` | `isReboot=false` |

---

### `internal/poller/probe_test.go` — Probe path selection

| # | Test name | SNMP response | Expected state |
|---|---|---|---|
| 22 | Engine OIDs supported | all 3 OIDs return values | `EngineProbed=true, UseEngineOIDs=true` |
| 23 | Engine OIDs return noSuchObject | engine OIDs error, sysUptime OK | `EngineProbed=true, UseEngineOIDs=false`, Path B seeded with sysUptime from same response |
| 24 | All OIDs fail (SNMP error) | GET returns error | `EngineProbed=false`, state unchanged |
| 25 | Already probed, skip probe | `EngineProbed=true` | no new GET for probe; use stored path |

---

### `internal/event/retryqueue_test.go`

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 26 | Write and read back | Write 3 events, read queue | 3 events returned in order |
| 27 | Drain all succeed | 3 queued events, all INSERT succeed | queue file empty after drain |
| 28 | Partial drain — DB fails mid-way | 3 events, 2nd INSERT fails | queue contains events 2 and 3 |
| 29 | Empty queue file | Drain with no queue file | no error, no-op |
| 30 | Corrupt queue file | Non-JSON line in queue | skip corrupt line, log warning, process rest |

---

### `internal/event/polllog_test.go` — Daily rotation & retention

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 31 | Write within same day | 5 writes, same date | all in one file `poll.YYYY-MM-DD.log` |
| 32 | Date rollover mid-run | Write at 23:59, advance clock to 00:01, write again | two separate dated files |
| 33 | Retention — delete old files | Files for last 35 days, retention=30 | files older than 30 days deleted, rest kept |
| 34 | Retention — keep forever | `log_retention_days=0` | no files deleted |
| 35 | Retention — no old files | All files within retention window | no deletions, no error |

---

### `internal/event/uptimeupsert_test.go` — Batch upsert

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 36 | Single batch | 499 devices | 1 batch sent |
| 37 | Exact batch boundary | 500 devices | 1 batch |
| 38 | Two batches | 501 devices | 2 batches |
| 39 | Path A row | `UseEngineOIDs=true` | `sys_uptime=NULL, engine_boots set` |
| 40 | Path B row | `UseEngineOIDs=false` | `engine_boots=NULL, sys_uptime set` |
| 41 | Upsert conflict | IP already exists | row updated, not duplicated |
| 42 | Batch fails, queued | DB error on batch | events written to `pg_uptime_retry.queue` |

---

### `internal/device/repository_test.go`

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 43 | DB available | DB returns 100 devices | devices loaded, cache file written |
| 44 | DB unavailable, cache exists | DB error, cache file present | cache loaded, warning logged |
| 45 | DB unavailable, no cache | DB error, no cache file | fatal error returned |
| 46 | DB returns empty list | 0 rows | warning logged, cache written with empty list |

---

### `internal/poller/uptime_test.go` — additional edge cases

| # | Test name | Input | Expected |
|---|---|---|---|
| 47 | Path A: boots wrap (0xFFFFFFFF → 0) | `prev.boots=0xFFFFFFFF, curr.boots=0` | `isReboot=true, method=engine_boots` |
| 48 | Path A: boots decreased unexpectedly | `prev.boots=10, curr.boots=5` | `isReboot=true, method=engine_boots`, warning logged |
| 49 | Path A: firmware downgrade, engine OIDs disappear | `UseEngineOIDs=true`, GET returns noSuchObject for engine OIDs | `UseEngineOIDs=false`, switch to Path B, no reboot emitted |
| 50 | Path B: sysUptime always 0 (buggy device) | `prev=0, curr=0, elapsed=900s` | `isReboot=false` (delta=0, treated as normal) |
| 51 | NTP clock jump forward past rollover threshold | `wallElapsed > ROLLOVER_THRESHOLD` but delta > 0 | gap check applies; if gap > threshold → gap_inferred |
| 52 | ConsecutiveFailures increments on SNMP error | 3 consecutive errors | `ConsecutiveFailures=3`, warning at threshold |
| 53 | ConsecutiveFailures resets on success | 3 errors then 1 success | `ConsecutiveFailures=0` |

---

### `internal/poller/probe_test.go` — additional probe cases

| # | Test name | SNMP response | Expected |
|---|---|---|---|
| 54 | One engine OID returns noSuchObject, other valid | `snmpEngineBoots=noSuchObject, snmpEngineTime=valid` | `UseEngineOIDs=false`, fallback to Path B |
| 55 | Probe: engine OIDs valid but sysUptime also fails | engine OIDs OK, sysUptime=error | `UseEngineOIDs=true`, Path A seeded; sysUptime not needed |

---

### `internal/poller/lockfile_test.go`

| # | Test name | Scenario | Expected |
|---|---|---|---|
| 56 | Lock acquired normally | No existing lock file | Lock created, released on exit |
| 57 | Stale lock from dead process | Lock file exists, PID in file is dead | Lock file overwritten, run proceeds |
| 58 | Live lock from running process | Lock file exists, PID is active | Exit immediately with warning |

---

## Verification

```bash
# Unit tests (no external deps)
go test ./internal/poller/... -run TestDetectReboot -v

# Full test suite
go test ./...

# Cross-compile for target
GOOS=linux GOARCH=386 go build -o pms-poller ./cmd/poller

# Integration test (requires Postgres + real/simulated SNMP device)
go test ./internal/device/... -tags integration
go test ./internal/state/... -tags integration

# Run locally
./pms-poller --config config.yaml

# Verify metrics endpoint
curl http://localhost:9090/metrics | grep poller_
```
