package state

import "time"

// DeviceState is the per-device persistent state written to LevelDB after each poll.
type DeviceState struct {
	// Probe result — determined on first poll, stored forever unless UseEngineOIDs flips.
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

	// Shared
	ConsecutiveFailures int // SNMP errors in a row; reset to 0 on success

	// Ping (only populated when enable_ping=true)
	LastPingSuccessAt time.Time // zero if never successfully pinged
	LastPingRTTMs     float64   // RTT from the last successful ping
}
