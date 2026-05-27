package poller

import (
	"time"

	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/state"
)

// RebootResult is the output of the reboot-detection functions.
type RebootResult struct {
	IsReboot        bool
	IsSuspected     bool
	DetectionMethod event.DetectionMethod
	EstimatedBoot   time.Time
	PrevValue       uint32
	CurrValue       uint32
}

// DetectConfig holds thresholds used by the detection functions.
type DetectConfig struct {
	RolloverThresholdSeconds        int // default 42520176 (~492 days)
	MaxValueStreakThreshold         int // default 3
	GapRebootThresholdSeconds       int // default 1800
	EngineTimeDriftToleranceSeconds int // default 300 — NTP slew on device can push engTime backwards slightly
}

// DetectRebootEngine implements Path A detection (snmpEngineBoots + snmpEngineTime).
// prev must already have EngineProbed=true. Pure function — no I/O.
func DetectRebootEngine(prev state.DeviceState, boots, engineTime uint32, now time.Time, cfg DetectConfig) (RebootResult, state.DeviceState) {
	next := prev
	next.LastEngineBoots = boots
	next.LastEngineTime = engineTime

	isReboot := false

	switch {
	case boots > prev.LastEngineBoots:
		isReboot = true
	case boots == 0 && prev.LastEngineBoots == 0xFFFFFFFF:
		// snmpEngineBoots wrapped (2^32 reboots)
		isReboot = true
	case boots < prev.LastEngineBoots && !(boots == 0 && prev.LastEngineBoots == 0xFFFFFFFF):
		// boots decreased unexpectedly
		isReboot = true
	case boots == prev.LastEngineBoots && engineTime < prev.LastEngineTime:
		// engineTime went backwards — could be NTP slew (small) or genuine reboot (large)
		regression := int64(prev.LastEngineTime) - int64(engineTime)
		if regression > int64(cfg.EngineTimeDriftToleranceSeconds) {
			isReboot = true
		}
	}

	if !isReboot {
		return RebootResult{}, next
	}

	estimatedBoot := now.Add(-time.Duration(engineTime) * time.Second)
	next.LastBootTime = estimatedBoot

	return RebootResult{
		IsReboot:        true,
		IsSuspected:     false,
		DetectionMethod: event.MethodEngineBoots,
		EstimatedBoot:   estimatedBoot,
		PrevValue:       prev.LastEngineBoots,
		CurrValue:       boots,
	}, next
}

// DetectRebootUptime implements Path B detection (sysUptime).
// prev must already have EngineProbed=true. Pure function — no I/O.
func DetectRebootUptime(prev state.DeviceState, current uint32, now time.Time, cfg DetectConfig) (RebootResult, state.DeviceState) {
	next := prev

	const maxUptime uint32 = 0xFFFFFFFF

	// Step 1 — stuck-MAX firmware bug
	if current == maxUptime {
		next.MaxValueStreak = prev.MaxValueStreak + 1
		next.LastSysUptime = current
		next.LastWallClock = now
		if next.MaxValueStreak >= cfg.MaxValueStreakThreshold {
			return RebootResult{}, next
		}
		// allow evaluation on first few hits
	} else {
		// Step 2 — reset streak on any non-MAX value
		next.MaxValueStreak = 0
	}

	// First poll — seed state, never emit reboot
	if prev.LastWallClock.IsZero() {
		next.LastSysUptime = current
		next.LastWallClock = now
		return RebootResult{}, next
	}

	// Step 3 — compute delta and wall elapsed
	delta := int64(current) - int64(prev.LastSysUptime)
	wallElapsed := now.Sub(prev.LastWallClock).Seconds()
	if wallElapsed < 0 {
		wallElapsed = 0
	}

	next.LastSysUptime = current
	next.LastWallClock = now

	rolloverThreshold := float64(cfg.RolloverThresholdSeconds)

	// Step 4a — 32-bit counter rollover
	if delta < 0 && wallElapsed >= rolloverThreshold {
		return RebootResult{}, next
	}

	// Step 4b — genuine reboot (uptime went backwards)
	if delta < 0 && wallElapsed < rolloverThreshold {
		estimatedBoot := now.Add(-time.Duration(float64(current)/100.0) * time.Second)
		next.LastBootTime = estimatedBoot
		return RebootResult{
			IsReboot:        true,
			IsSuspected:     false,
			DetectionMethod: event.MethodSysUptime,
			EstimatedBoot:   estimatedBoot,
			PrevValue:       prev.LastSysUptime,
			CurrValue:       current,
		}, next
	}

	// Step 4c — delta >= 0: check for gap reboot (poller outage)
	deltaSeconds := float64(delta) / 100.0
	gap := wallElapsed - deltaSeconds
	if gap > float64(cfg.GapRebootThresholdSeconds) {
		estimatedBoot := now.Add(-time.Duration(float64(current)/100.0) * time.Second)
		next.LastBootTime = estimatedBoot
		return RebootResult{
			IsReboot:        true,
			IsSuspected:     true,
			DetectionMethod: event.MethodGapInferred,
			EstimatedBoot:   estimatedBoot,
			PrevValue:       prev.LastSysUptime,
			CurrValue:       current,
		}, next
	}

	return RebootResult{}, next
}

// SeedEngineState stores the initial Path A values without emitting a reboot event.
func SeedEngineState(prev state.DeviceState, boots, engineTime uint32) state.DeviceState {
	next := prev
	next.EngineProbed = true
	next.UseEngineOIDs = true
	next.LastEngineBoots = boots
	next.LastEngineTime = engineTime
	return next
}

// SeedUptimeState stores the initial Path B values without emitting a reboot event.
func SeedUptimeState(prev state.DeviceState, sysUptime uint32, now time.Time) state.DeviceState {
	next := prev
	next.EngineProbed = true
	next.UseEngineOIDs = false
	next.LastSysUptime = sysUptime
	next.LastWallClock = now
	return next
}
