# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Go daemon that polls ~25,000 SNMP-enabled network devices (Huawei, ZTE, Fiberhome, Nokia, etc.) every 15 minutes to detect device reboot events. It stores persistent state in LevelDB and loads its device list from PostgreSQL, with a local file cache so polling continues even when PostgreSQL is unavailable.

## Build & Run

```bash
make build    # cross-compile for linux/386 → ./poll-uptime
make deploy   # build + sftp to dv02:/home/pms/online/sbin/poll-uptime
make test     # run all unit tests

# Run a single test
go test ./internal/poller -run TestSysUptimeRollover
```

## Architecture

The application has three main concerns:

1. **Device list management** — loads from PostgreSQL (`SELECT ip, name FROM device`), persists to a local file, falls back to the file if Postgres is unreachable on startup or reload.

2. **SNMP polling engine** — polls each device's `sysUptime` OID on a 15-minute cron schedule. Must handle:
   - Normal reboot detection (new sysUptime < previous sysUptime)
   - **32-bit counter rollover** (~497 days): sysUptime wraps to 0 and climbs again — distinguish from a genuine reboot using elapsed wall-clock time
   - **Firmware bug — stuck MAX value**: some devices report sysUptime frozen at `0xFFFFFFFF`; treat the first occurrence as stale and suppress false reboot events on subsequent polls

3. **State store (LevelDB)** — keyed by device IP, stores last-seen sysUptime and the wall-clock timestamp of that reading so rollover math is possible across process restarts.

## Key Design Constraints

- Must survive PostgreSQL downtime: device list file is the source of truth once loaded.
- 25,000 devices × 15-minute window requires concurrent polling; use a worker pool with a configurable concurrency limit.
- Multi-vendor devices may return sysUptime in different SNMP community strings or require SNMPv3; the device struct should carry auth config.
- Reboot events should be emitted (log line / channel / webhook) with: device IP, device name, estimated reboot time, detection timestamp.
