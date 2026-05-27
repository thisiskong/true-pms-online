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
│   │   ├── model.go                 # Device struct
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
├── DESIGN.md
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
    ReprobeAt       time.Time  // zero = never re-probe

    // Path A — snmpEngineBoots/snmpEngineTime
    LastEngineBoots uint32
    LastEngineTime  uint32     // seconds

    // Path B — sysUptime fallback
    LastSysUptime   uint32
    LastWallClock   time.Time
    MaxValueStreak  int        // consecutive 0xFFFFFFFF hits; reset to 0 on any non-MAX value
    LastBootTime    time.Time  // estimated boot time; updated on every detected reboot

    // Shared
    ConsecutiveFailures int    // SNMP errors in a row; reset to 0 on success
}
```

### `RebootEvent` + `PollRecord` (internal/event/model.go)

```go
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
    // PrevValue/CurrValue: snmpEngineBoots for engine_boots, sysUptime timeticks otherwise
    PrevValue       uint32
    CurrValue       uint32
    IsSuspected     bool            // true only when DetectionMethod == MethodGapInferred
    DetectionMethod DetectionMethod
}

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
    DetectionMethod DetectionMethod  `json:"detection_method,omitempty"`
    BootTime        *time.Time       `json:"boot_time,omitempty"`
}
```

---

## Output Files

### Poll log — `<poll_log_dir>/poll.YYYY-MM-DD.log`

One NDJSON record per device per run. Daily rotation (in-process). Deleted after `log_retention_days`.

```json
{"timestamp":"2026-05-27T10:00:01Z","ip":"10.0.0.1","name":"HW-SW-01","engine_boots":3,"engine_time":7200,"is_reboot":false}
{"timestamp":"2026-05-27T10:00:02Z","ip":"10.0.0.2","name":"ZTE-OLT-03","sys_uptime":500,"is_reboot":true,"detection_method":"sys_uptime","boot_time":"2026-05-27T09:58:47Z"}
{"timestamp":"2026-05-27T10:00:03Z","ip":"10.0.0.3","name":"FH-ONU-07","error":"snmp timeout","is_reboot":false}
```

### Reboot event log — `<reboot_log_dir>/reboot.YYYY-MM-DD.log`

One NDJSON record per reboot event only. Daily rotation. Deleted after `log_retention_days`.

```json
{"timestamp":"2026-05-27T10:00:02Z","ip":"10.0.0.2","name":"ZTE-OLT-03","boot_time":"2026-05-27T09:58:47Z","is_suspected":false,"detection_method":"engine_boots","prev_value":5,"curr_value":6}
{"timestamp":"2026-05-27T10:15:07Z","ip":"10.0.1.5","name":"HW-OLT-12","boot_time":"2026-05-27T10:10:00Z","is_suspected":true,"detection_method":"gap_inferred","prev_value":1234567,"curr_value":30000}
```

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
type EventEmitter interface {
    Emit(ctx context.Context, event RebootEvent) error
    Close() error
}

// internal/event/polllog.go
type PollLogger interface {
    Write(record PollRecord) error  // goroutine-safe; rotates file on date change
    Close() error
}

// internal/snmp/client.go
type SNMPClient interface {
    Get(ctx context.Context, device Device, oids []string) (map[string]uint32, error)
}
```

---

## OIDs Used

| OID | Name | Used when |
|---|---|---|
| `1.3.6.1.6.3.10.2.1.2.0` | `snmpEngineBoots` | Device supports it (probed once on first poll) |
| `1.3.6.1.6.3.10.2.1.3.0` | `snmpEngineTime` | Device supports it (probed once on first poll) |
| `1.3.6.1.2.1.1.3.0` | `sysUptime` | Fallback when engine OIDs unavailable |

---

## Reboot-Detection Algorithm

### Probe (first poll per device) — single GET, all 3 OIDs

```
GET ["1.3.6.1.6.3.10.2.1.2.0", "1.3.6.1.6.3.10.2.1.3.0", "1.3.6.1.2.1.1.3.0"]
```

- Both engine OIDs return valid integers → `UseEngineOIDs=true`, Path A
- Either engine OID returns `noSuchObject` → `UseEngineOIDs=false`, seed Path B from sysUptime in same response
- All OIDs fail (timeout/error) → `EngineProbed=false`, retry probe next run

Regular polls: Path A sends 2 OIDs, Path B sends 1 OID — always 1 request per device.

### Path A — snmpEngineBoots + snmpEngineTime (preferred)

```
IF boots > prev.LastEngineBoots                         → reboot (certain)
IF boots == 0 AND prev == 0xFFFFFFFF                    → counter wrapped, reboot
IF boots == prev AND engineTime < prev.LastEngineTime   → firmware anomaly, reboot
IF boots < prev (and not wrap)                          → counter decreased, reboot + warning
ELSE                                                    → normal
```

Firmware downgrade (engine OIDs disappear): flip `UseEngineOIDs=false`, switch to Path B immediately.

### Path B — sysUptime fallback

```
ROLLOVER_THRESHOLD = 42,520,176s (~492 days = 99% of 32-bit timetick period)
MAX_UPTIME         = 0xFFFFFFFF

1. current == MAX_UPTIME → increment MaxValueStreak
   streak >= 3           → suppress, return isReboot=false

2. Non-MAX → reset MaxValueStreak = 0

3. delta = int64(current) - int64(prev)   // int64 to avoid uint32 wrap
   wallElapsed = max(0, now - prev.LastWallClock)   // clamp negative (NTP jump)

4a. delta < 0 AND wallElapsed >= ROLLOVER_THRESHOLD → rollover, no event
4b. delta < 0 AND wallElapsed <  ROLLOVER_THRESHOLD → reboot (certain)
4c. delta >= 0:
    gap = wallElapsed - (delta / 100.0)
    gap > 1800s  → reboot during poller outage (isSuspected=true, method=gap_inferred)
    gap <= 1800s → normal
```

---

## Postgres Tables

### `device` table (pre-existing — add columns as needed)

```sql
ALTER TABLE device ADD COLUMN IF NOT EXISTS port           SMALLINT     DEFAULT 161;
ALTER TABLE device ADD COLUMN IF NOT EXISTS snmp_version   SMALLINT     NOT NULL DEFAULT 2;
ALTER TABLE device ADD COLUMN IF NOT EXISTS community      VARCHAR(128);
ALTER TABLE device ADD COLUMN IF NOT EXISTS security_name  VARCHAR(128);
ALTER TABLE device ADD COLUMN IF NOT EXISTS security_level VARCHAR(32);
ALTER TABLE device ADD COLUMN IF NOT EXISTS auth_protocol  VARCHAR(16);
ALTER TABLE device ADD COLUMN IF NOT EXISTS auth_key       TEXT;
ALTER TABLE device ADD COLUMN IF NOT EXISTS priv_protocol  VARCHAR(16);
ALTER TABLE device ADD COLUMN IF NOT EXISTS priv_key       TEXT;
```

Device list query:
```sql
SELECT ip, name, port, snmp_version, community,
       security_name, security_level, auth_protocol, auth_key, priv_protocol, priv_key
FROM device
```

### `device_reboot_event` (create once)

```sql
CREATE TABLE device_reboot_event (
    id               BIGSERIAL    PRIMARY KEY,
    detected_at      TIMESTAMPTZ  NOT NULL,
    ip               VARCHAR(45)  NOT NULL,
    name             TEXT         NOT NULL,
    boot_time        TIMESTAMPTZ,
    is_suspected     BOOLEAN      NOT NULL DEFAULT FALSE,
    detection_method VARCHAR(32)  NOT NULL,
    prev_value       BIGINT,
    curr_value       BIGINT
);
CREATE INDEX ON device_reboot_event (ip, detected_at);
```

### `device_last_uptime` (create once)

```sql
CREATE TABLE device_last_uptime (
    ip              VARCHAR(45)  PRIMARY KEY,
    name            TEXT         NOT NULL,
    sys_uptime      BIGINT,
    engine_boots    BIGINT,
    engine_time     BIGINT,
    polled_at       TIMESTAMPTZ  NOT NULL,
    poll_method     VARCHAR(32)  NOT NULL,   -- 'engine_oids' | 'sys_uptime'
    last_reboot_at  TIMESTAMPTZ
);
```

Upsert runs in batches of 500 after the poll cycle completes (`pgx.Batch`).

---

## Worker Pool

- 500 workers (default, configurable)
- Per-device `context.WithTimeout(ctx, snmp_timeout)`
- Buffered `jobCh` → workers → buffered `resultCh`
- Top-level 14-minute deadline context
- PID lock file prevents overlapping cron runs

---

## Retry Queue (Postgres outage resilience)

Failed `device_reboot_event` INSERTs and `device_last_uptime` batch upserts are written to local NDJSON queue files (`pg_retry.queue`, `pg_uptime_retry.queue`). On each run start, the queue is drained before the poll cycle. Queue files are human-readable and operator-clearable.

---

## Prometheus Metrics (optional Pushgateway)

Pushed at end of each run if `pushgateway_url` is set:

| Metric | Description |
|---|---|
| `pms_poll_devices_total` | Total devices polled |
| `pms_poll_success_total` | Devices that responded |
| `pms_poll_error_total` | Timeouts / errors |
| `pms_poll_reboot_total` | Reboot events detected |
| `pms_poll_cycle_duration_seconds` | Wall-clock cycle time |
| `pms_poll_last_run_timestamp` | Unix timestamp of completion |

---

## Configuration (`config.yaml`)

```yaml
concurrency: 500
snmp_timeout: 5s
snmp_retries: 1                       # total attempts = snmp_retries + 1
lock_file: "/var/run/pms-poller.lock"
leveldb_path: "./data/state.db"
device_cache_file: "./data/devices.json"
poll_log_dir: "./logs"
reboot_log_dir: "./logs"
log_retention_days: 30                # 0 = keep forever
log_level: "info"
postgres_dsn: ""                      # use POLLER_POSTGRES_DSN env var
postgres_timeout: 10s
reboot_pg_table: ""                   # disabled if empty
reboot_pg_timeout: 3s
pg_retry_queue_file: "./data/pg_retry.queue"
uptime_pg_table: "device_last_uptime"
uptime_batch_size: 500
pg_uptime_retry_queue_file: "./data/pg_uptime_retry.queue"
rollover_threshold_seconds: 42520176
max_value_streak_threshold: 3
max_consecutive_failures: 10
gap_reboot_threshold_seconds: 1800
prune_removed_devices: true
default_port: 161
pushgateway_url: ""
pushgateway_job: "pms_poller"
```

---

## Libraries

| Concern | Library |
|---|---|
| SNMP | `github.com/gosnmp/gosnmp` |
| LevelDB | `github.com/syndtr/goleveldb/leveldb` |
| PostgreSQL | `github.com/jackc/pgx/v5` |
| Config | `github.com/spf13/viper` |
| Logging | `log/slog` (stdlib) |
| Metrics | `github.com/prometheus/client_golang` |

No CGo — required for `GOOS=linux GOARCH=386` cross-compilation.

---

## Build & Test

```bash
# Unit tests
go test ./...

# Cross-compile for target
GOOS=linux GOARCH=386 go build -o pms-poller ./cmd/poller

# Integration tests (require Postgres)
go test ./internal/device/... -tags integration
go test ./internal/state/... -tags integration
```
