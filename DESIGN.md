# Design: Go SNMP Reboot Poller (`true-pms-online`)

## Context

A Go daemon that polls ~25,000 SNMP-enabled network devices every 15 minutes and emits reboot events. The primary design challenge is correctness: distinguishing a genuine reboot from a 32-bit counter rollover, a stuck-MAX firmware bug, or device clock anomalies (NTP slew, countdown-timer engTime), while sustaining 25,000 concurrent UDP polls within a 15-minute window.

---

## Deployment Model

**Short-lived process invoked by system cron every 15 minutes.** The binary starts, loads devices, polls all 25k devices concurrently, writes state to LevelDB, then exits.

```
# /etc/cron.d/poll-uptime
*/15 * * * * root /home/pms/online/sbin/poll-uptime --config /etc/pms/poll-uptime.yaml
```

A **PID lock file** (`/var/run/pms-poller.lock`) prevents overlapping runs. On startup: if file exists and PID is alive → exit. If PID is dead (stale lock) → overwrite and continue. On exit: delete lock file.

---

## Directory Layout

```
true-pms-online/
├── cmd/poll-uptime/           # Entry point: load config, load devices, run poll cycle, exit
│   ├── main.go
│   ├── inspect.go               # --inspect-ip diagnostic mode
│   └── lockfile.go
├── internal/
│   ├── config/config.go         # Config struct + Viper loader
│   ├── device/
│   │   ├── model.go             # Device struct (flat, supports v2c + v3)
│   │   ├── repository.go        # CompositeRepository: DB → file cache fallback
│   │   ├── postgres.go          # pgx implementation
│   │   └── filecache.go         # JSON file persistence
│   ├── state/
│   │   ├── model.go             # DeviceState struct
│   │   ├── store.go             # StateStore interface
│   │   └── leveldb.go           # LevelDB implementation
│   ├── snmp/
│   │   ├── client.go            # SNMPClient interface + gosnmp wrapper
│   │   └── oid.go               # OID constants + ProbeOIDs / EngineOIDs / UptimeOIDs slices
│   ├── poller/
│   │   ├── uptime.go            # DetectRebootEngine + DetectRebootUptime — pure functions
│   │   ├── worker.go            # Worker pool + path A/B handlers
│   │   └── poller.go            # RunPollCycle — wires pool, state, emitter
│   ├── event/
│   │   ├── model.go             # RebootEvent, PollRecord structs
│   │   ├── localtime.go         # LocalTime: time.Time marshalled as "2006-01-02T15:04:05" (no TZ)
│   │   ├── emitter.go           # EventEmitter interface + MultiEmitter
│   │   ├── logger.go            # slog structured-log emitter
│   │   ├── rebootlog.go         # reboot event → daily-rotated NDJSON file
│   │   ├── postgres.go          # reboot event → Postgres INSERT + retry queue drain
│   │   ├── retryqueue.go        # file-based pending queue (NDJSON) for failed inserts
│   │   ├── polllog.go           # poll result per device → daily-rotated NDJSON file
│   │   └── uptimeupsert.go      # batch upsert poll results → device_last_uptime
│   └── metrics/
│       └── pushgateway.go       # Prometheus Pushgateway client (optional)
├── config.yaml
├── go.mod / go.sum
├── Makefile
└── DESIGN.md
```

---

## Key Structs

### `Device` (internal/device/model.go)

```go
// Flat struct — all fields map directly to device table columns.
// v3-specific fields are empty string for v2c devices.
type Device struct {
    IP            string
    Name          string
    Port          uint16
    SNMPVersion   int    // 2 (v2c) or 3 (v3)
    Community     string // v2c only
    SecurityName  string // v3
    SecurityLevel string // v3: "noAuthNoPriv" | "authNoPriv" | "authPriv"
    AuthProtocol  string // v3: "MD5" | "SHA" | "SHA256"
    AuthKey       string
    PrivProtocol  string // v3: "DES" | "AES" | "AES256"
    PrivKey       string
}
```

### `DeviceState` (internal/state/model.go)

```go
type DeviceState struct {
    EngineProbed  bool
    UseEngineOIDs bool
    ReprobeAt     time.Time // zero = never re-probe

    // Path A — snmpEngineBoots / snmpEngineTime
    LastEngineBoots uint32
    LastEngineTime  uint32 // seconds

    // Path B — sysUptime
    LastSysUptime  uint32
    LastWallClock  time.Time
    MaxValueStreak int       // consecutive 0xFFFFFFFF readings; reset on any non-MAX value
    LastBootTime   time.Time // estimated boot time, updated on each detected reboot

    ConsecutiveFailures int
}
```

### `RebootEvent` + `PollRecord` (internal/event/model.go)

```go
type DetectionMethod string

const (
    MethodEngineBoots DetectionMethod = "engine_boots" // Path A: boots incremented
    MethodSysUptime   DetectionMethod = "sys_uptime"   // Path B: uptime went backwards
    MethodGapInferred DetectionMethod = "gap_inferred" // Path B: inferred from poller outage
)

type RebootEvent struct {
    DeviceIP        string
    DeviceName      string
    EstimatedBoot   time.Time
    DetectedAt      time.Time
    PrevValue       uint32          // snmpEngineBoots or sysUptime timeticks
    CurrValue       uint32
    IsSuspected     bool            // true only for gap_inferred
    DetectionMethod DetectionMethod
}

type PollRecord struct {
    Timestamp       LocalTime        `json:"timestamp"`
    IP              string           `json:"ip"`
    Name            string           `json:"name"`
    SysUptime       *uint32          `json:"sys_uptime,omitempty"`   // always set when device responds
    EngineBoots     *uint32          `json:"engine_boots,omitempty"` // Path A only
    EngineTime      *uint32          `json:"engine_time,omitempty"`  // Path A only
    Error           string           `json:"error,omitempty"`
    IsReboot        bool             `json:"is_reboot"`
    IsSuspected     bool             `json:"is_suspected,omitempty"`
    DetectionMethod DetectionMethod  `json:"detection_method,omitempty"`
    BootTime        *LocalTime       `json:"boot_time,omitempty"`
}
```

---

## Output Files

### Poll log — `<poll_log_dir>/uptime.log` (active) / `uptime.YYYY-MM-DD.log` (archived)

One NDJSON record per device per run. Active file has no date suffix; on UTC midnight rotation the file is renamed with the date. Deleted after `log_retention_days`.

```json
{"timestamp":"2026-05-27T10:00:01","ip":"10.0.0.1","name":"HW-SW-01","sys_uptime":3078000,"engine_boots":3,"engine_time":7200,"is_reboot":false}
{"timestamp":"2026-05-27T10:00:02","ip":"10.0.0.2","name":"ZTE-OLT-03","sys_uptime":500,"engine_boots":6,"engine_time":500,"is_reboot":true,"detection_method":"engine_boots","boot_time":"2026-05-27T09:58:47"}
{"timestamp":"2026-05-27T10:00:03","ip":"10.0.0.3","name":"FH-ONU-07","error":"snmp timeout","is_reboot":false}
```

### Reboot event log — `<reboot_log_dir>/reboot.log` (active) / `reboot.YYYY-MM-DD.log` (archived)

One NDJSON record per reboot event only. Active file has no date suffix; renamed with date on rotation. Deleted after `log_retention_days`.

```json
{"timestamp":"2026-05-27T10:00:02","ip":"10.0.0.2","name":"ZTE-OLT-03","boot_time":"2026-05-27T09:58:47","is_suspected":false,"detection_method":"engine_boots","prev_value":5,"curr_value":6}
{"timestamp":"2026-05-27T10:15:07","ip":"10.0.1.5","name":"HW-OLT-12","boot_time":"2026-05-27T10:10:00","is_suspected":true,"detection_method":"gap_inferred","prev_value":1234567,"curr_value":30000}
```

### App log — `<log_output>/poll-uptime.log` (active) / `poll-uptime.YYYY-MM-DD.log` (archived) *(when `log_rotate: true`)*

Structured application log (slog JSON or text). Active file has no date suffix; renamed with date on rotation. Deleted after `log_retention_days`. When `log_output` is `stderr` or `stdout`, no file is written.

All timestamps use `"2006-01-02T15:04:05"` format (no timezone suffix).

---

## OIDs Used

| OID | Name | Fetched when |
|---|---|---|
| `1.3.6.1.6.3.10.2.1.2.0` | `snmpEngineBoots` | Probe + every Path A poll |
| `1.3.6.1.6.3.10.2.1.3.0` | `snmpEngineTime` | Probe + every Path A poll |
| `1.3.6.1.2.1.1.3.0` | `sysUptime` | Probe + every poll (Path A and B) |

Path A GET requests 3 OIDs so `sys_uptime` is always populated in `device_last_uptime`.

---

## Reboot-Detection Algorithm

### Probe (first poll per device) — single GET, all 3 OIDs

- Both engine OIDs return valid integers → `UseEngineOIDs=true`, Path A
- Either engine OID returns `noSuchObject` → `UseEngineOIDs=false`, seed Path B from sysUptime in same response
- All OIDs fail (timeout/error) → `EngineProbed=false`, retry probe next run

### Path A — snmpEngineBoots + snmpEngineTime (preferred)

```
IF boots > prev.LastEngineBoots          → reboot (certain)
IF boots == 0 AND prev == 0xFFFFFFFF     → counter wrapped, reboot
IF boots < prev (and not wrap)           → counter decreased, reboot
IF boots == prev                         → NOT a reboot (NTP slew or countdown-timer firmware)
ELSE                                     → normal
```

`snmpEngineTime` moving backwards with `boots` unchanged is never treated as a reboot. Small regressions are NTP slew; large regressions indicate countdown-timer firmware bugs (e.g. some Huawei models). Both are benign as long as `boots` doesn't change.

**Path A → Path B fallback:**
- **Firmware downgrade**: engine OIDs return `noSuchObject` on a regular poll → flip `UseEngineOIDs=false` immediately, seed Path B from sysUptime in the same response.

### Path B — sysUptime fallback

```
ROLLOVER_THRESHOLD = 42,520,176s (~492 days = 99% of 32-bit timetick period)
MAX_UPTIME         = 0xFFFFFFFF

1. current == MAX_UPTIME → increment MaxValueStreak
   streak >= max_value_streak_threshold (default 3) → suppress, no event

2. Non-MAX → reset MaxValueStreak = 0

3. delta = int64(current) - int64(prev)          // int64 prevents uint32 silent wrap
   wallElapsed = max(0, now - prev.LastWallClock) // clamp negative (NTP jump guard)

4a. delta < 0 AND wallElapsed >= ROLLOVER_THRESHOLD → rollover, no event
4b. delta < 0 AND wallElapsed <  ROLLOVER_THRESHOLD → reboot (certain)
4c. delta >= 0:
    gap = wallElapsed - (delta / 100.0)
    gap > gap_reboot_threshold_seconds (default 1800s)
        → reboot during poller outage (isSuspected=true, method=gap_inferred)
    else → normal
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

### `device_reboot_event` (create once)

```sql
CREATE TABLE device_reboot_event (
    id               BIGSERIAL    PRIMARY KEY,
    detected_at      TIMESTAMP    NOT NULL,
    ip               VARCHAR(45)  NOT NULL,
    name             TEXT         NOT NULL,
    boot_time        TIMESTAMP,
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
    sys_uptime      BIGINT,                  -- always set when device responds
    engine_boots    BIGINT,                  -- NULL for Path B devices
    engine_time     BIGINT,                  -- NULL for Path B devices
    polled_at       TIMESTAMP    NOT NULL,
    poll_method     VARCHAR(32)  NOT NULL,   -- 'engine_oids' | 'sys_uptime'
    last_reboot_at  TIMESTAMP
);
```

Upsert runs in batches of 500 after each poll cycle (`pgx.Batch`).

---

## Worker Pool

- 500 workers (default, configurable via `concurrency`)
- Per-device `context.WithTimeout(ctx, snmp_timeout)`
- Buffered `jobCh` → workers → buffered `resultCh`
- Top-level 14-minute deadline context
- PID lock file prevents overlapping cron runs

---

## Retry Queue (Postgres outage resilience)

Failed `device_reboot_event` INSERTs and `device_last_uptime` batch upserts are written to local NDJSON queue files (`pg_retry.queue`, `pg_uptime_retry.queue`). On each run start the queue is drained before the poll cycle. Files are human-readable and operator-clearable.

---

## Diagnostic Mode (`--inspect-ip`)

```bash
poll-uptime --config config.yaml --inspect-ip 10.0.1.5
```

Read-only. Dumps LevelDB state for the IP as JSON, runs a live SNMP GET, and prints what the detection algorithm would decide and why. Does not write state or emit events.

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
snmp_retries: 1
lock_file: "/var/run/pms-poller.lock"
leveldb_path: "./data/state.db"
device_cache_file: "./data/devices.json"
poll_log_dir: "./logs"
reboot_log_dir: "./logs"
log_retention_days: 30
log_level: "info"
log_format: "json"       # "json" or "text"
log_output: "stderr"     # "stderr", "stdout", or a directory path
log_rotate: false        # daily rotation to <log_output>/poll-uptime.YYYY-MM-DD.log
postgres_dsn: ""                      # use POLLER_POSTGRES_DSN env var
postgres_timeout: 10s
device_query: |                       # SQL to load device list
  SELECT ip, name, ...
reboot_pg_table: "device_reboot_event"
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

## Build & Deploy

```bash
make build    # cross-compile for linux/386 → ./poll-uptime
make test     # run all unit tests
make deploy   # build + sftp to dv02:/home/pms/online/sbin/poll-uptime
```
