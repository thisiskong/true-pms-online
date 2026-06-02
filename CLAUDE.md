# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

```
true-pms-online/
└── poller/
    ├── uptime/    # Go daemon: polls SNMP devices every 15 min, detects reboots
    └── snmptk/    # Go toolkit: SNMP helpers for PON/FTTx traffic collection
```

Each sub-project is an independent Go module with its own `go.mod`.

## poller/uptime — SNMP reboot poller

The primary sub-project. Full architecture, commands, and design constraints are documented in [poller/uptime/CLAUDE.md](poller/uptime/CLAUDE.md).

Quick reference:

```bash
# Run from poller/uptime/
make build    # cross-compile linux/386 → ./poll-uptime
make test     # run all unit tests
make deploy   # build + sftp to dv02:/home/pms/online/sbin/poll-uptime

# Single test
go test ./internal/poller -run TestSysUptimeRollover
```

## poller/snmptk — SNMP toolkit

Helper library for collecting PON/FTTx traffic via SNMP. Contains `mapSnmpVar`, `mapGponSnmpVar`, OID list builders for Dot0 and PonPort. Currently contains hardcoded OID mappings that are candidates for configuration.

## Cross-cutting notes

- **Target platform**: `GOOS=linux GOARCH=386` — no CGo anywhere in either project.
- **Go version**: 1.26+ (see `poller/uptime/go.mod`).
- After any code change in either sub-project, run `go build ./...` from within that sub-project's directory to verify compilation.
