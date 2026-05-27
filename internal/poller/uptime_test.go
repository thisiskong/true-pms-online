package poller

import (
	"testing"
	"time"

	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/state"
)

var defaultDetectCfg = DetectConfig{
	RolloverThresholdSeconds:  42520176,
	MaxValueStreakThreshold:   3,
	GapRebootThresholdSeconds: 1800,
}

var baseTime = time.Date(2026, 5, 27, 10, 0, 0, 0, time.UTC)

// ---- Path A (snmpEngineBoots) tests ----

func TestDetectRebootEngine_Normal(t *testing.T) {
	prev := state.DeviceState{
		EngineProbed:    true,
		UseEngineOIDs:   true,
		LastEngineBoots: 5,
		LastEngineTime:  100,
	}
	result, next := DetectRebootEngine(prev, 5, 200, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot")
	}
	if next.LastEngineBoots != 5 || next.LastEngineTime != 200 {
		t.Fatal("state not updated")
	}
}

func TestDetectRebootEngine_SingleReboot(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 5, LastEngineTime: 7200}
	result, _ := DetectRebootEngine(prev, 6, 300, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot")
	}
	if result.DetectionMethod != event.MethodEngineBoots {
		t.Fatalf("expected engine_boots, got %s", result.DetectionMethod)
	}
	if result.PrevValue != 5 || result.CurrValue != 6 {
		t.Fatal("wrong prev/curr values")
	}
}

func TestDetectRebootEngine_MultipleReboots(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 5, LastEngineTime: 7200}
	result, _ := DetectRebootEngine(prev, 8, 300, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot")
	}
}

func TestDetectRebootEngine_EngineTimeBackwards(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 5, LastEngineTime: 500}
	result, _ := DetectRebootEngine(prev, 5, 100, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot (engineTime went backwards)")
	}
}

func TestDetectRebootEngine_BothZero(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 0, LastEngineTime: 0}
	result, _ := DetectRebootEngine(prev, 0, 0, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot for same-zero state")
	}
}

func TestDetectRebootEngine_BootsWrap(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 0xFFFFFFFF, LastEngineTime: 500}
	result, _ := DetectRebootEngine(prev, 0, 100, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot on boots counter wrap")
	}
}

func TestDetectRebootEngine_BootsDecreased(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 10, LastEngineTime: 500}
	result, _ := DetectRebootEngine(prev, 5, 600, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot when boots decreased")
	}
}

func TestDetectRebootEngine_EstimatedBoot(t *testing.T) {
	prev := state.DeviceState{LastEngineBoots: 5, LastEngineTime: 7200}
	result, _ := DetectRebootEngine(prev, 6, 3600, baseTime, defaultDetectCfg)
	expected := baseTime.Add(-3600 * time.Second)
	if !result.EstimatedBoot.Equal(expected) {
		t.Fatalf("expected boot time %v, got %v", expected, result.EstimatedBoot)
	}
}

// ---- Path B (sysUptime) tests ----

func TestDetectRebootUptime_FirstPoll(t *testing.T) {
	prev := state.DeviceState{}
	result, next := DetectRebootUptime(prev, 1000, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("first poll should not emit reboot")
	}
	if next.LastSysUptime != 1000 {
		t.Fatal("state not seeded")
	}
	if next.LastWallClock.IsZero() {
		t.Fatal("LastWallClock not set")
	}
}

func TestDetectRebootUptime_Normal(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 1000,
		LastWallClock: baseTime.Add(-10 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 2000, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot")
	}
}

func TestDetectRebootUptime_DirectReboot(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 9000000,
		LastWallClock: baseTime.Add(-600 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 500, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot")
	}
	if result.DetectionMethod != event.MethodSysUptime {
		t.Fatalf("expected sys_uptime, got %s", result.DetectionMethod)
	}
	if result.IsSuspected {
		t.Fatal("expected not suspected")
	}
}

func TestDetectRebootUptime_ZeroOnFreshBoot(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 5000000,
		LastWallClock: baseTime.Add(-600 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 0, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot when uptime resets to 0")
	}
}

func TestDetectRebootUptime_Rollover(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 4294900000,
		LastWallClock: baseTime.Add(-time.Duration(43000000) * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 100000, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot on legitimate rollover")
	}
}

func TestDetectRebootUptime_RolloverThresholdNotReached(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 4294900000,
		LastWallClock: baseTime.Add(-time.Duration(30000000) * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 100000, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot (wall elapsed < rollover threshold)")
	}
}

func TestDetectRebootUptime_StuckMaxFirst(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime:  0xFFFFFFFE,
		LastWallClock:  baseTime.Add(-900 * time.Second),
		MaxValueStreak: 0,
	}
	result, next := DetectRebootUptime(prev, 0xFFFFFFFF, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot on first MAX hit")
	}
	if next.MaxValueStreak != 1 {
		t.Fatalf("expected streak=1, got %d", next.MaxValueStreak)
	}
}

func TestDetectRebootUptime_StuckMaxSuppressed(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime:  0xFFFFFFFF,
		LastWallClock:  baseTime.Add(-900 * time.Second),
		MaxValueStreak: 3,
	}
	result, next := DetectRebootUptime(prev, 0xFFFFFFFF, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected suppressed after streak >= threshold")
	}
	if next.MaxValueStreak != 4 {
		t.Fatalf("expected streak=4, got %d", next.MaxValueStreak)
	}
}

func TestDetectRebootUptime_StuckMaxRecovery(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime:  0xFFFFFFFF,
		LastWallClock:  baseTime.Add(-900 * time.Second),
		MaxValueStreak: 3,
	}
	_, next := DetectRebootUptime(prev, 500, baseTime, defaultDetectCfg)
	if next.MaxValueStreak != 0 {
		t.Fatalf("expected streak reset to 0, got %d", next.MaxValueStreak)
	}
}

func TestDetectRebootUptime_GapReboot(t *testing.T) {
	// wall elapsed = 7200s, uptime delta = 100s → gap = 7100s > 1800s
	prev := state.DeviceState{
		LastSysUptime: 10000,
		LastWallClock: baseTime.Add(-7200 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 20000, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected gap reboot")
	}
	if result.DetectionMethod != event.MethodGapInferred {
		t.Fatalf("expected gap_inferred, got %s", result.DetectionMethod)
	}
	if !result.IsSuspected {
		t.Fatal("expected isSuspected=true")
	}
}

func TestDetectRebootUptime_GapWithinThreshold(t *testing.T) {
	// wall = 2000s, uptime delta = 1900s → gap = 100s < 1800s
	prev := state.DeviceState{
		LastSysUptime: 10000,
		LastWallClock: baseTime.Add(-2000 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 200000, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot when gap within threshold")
	}
}

func TestDetectRebootUptime_GapJustAboveThreshold(t *testing.T) {
	// gap = 1801s (just above 1800s threshold) → reboot
	wallElapsedSec := 3601
	uptimeDeltaSec := wallElapsedSec - 1801
	uptimeDeltaTicks := uint32(uptimeDeltaSec * 100)
	prev := state.DeviceState{
		LastSysUptime: 10000,
		LastWallClock: baseTime.Add(-time.Duration(wallElapsedSec) * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 10000+uptimeDeltaTicks, baseTime, defaultDetectCfg)
	if !result.IsReboot {
		t.Fatal("expected reboot when gap just above threshold")
	}
}

func TestDetectRebootUptime_GapAtExactThreshold(t *testing.T) {
	// gap exactly = 1800s → no reboot (threshold is exclusive: gap must be > 1800)
	wallElapsedSec := 3600
	uptimeDeltaSec := wallElapsedSec - 1800
	uptimeDeltaTicks := uint32(uptimeDeltaSec * 100)
	prev := state.DeviceState{
		LastSysUptime: 10000,
		LastWallClock: baseTime.Add(-time.Duration(wallElapsedSec) * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 10000+uptimeDeltaTicks, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("expected no reboot when gap equals threshold (exclusive boundary)")
	}
}

func TestDetectRebootUptime_NTPJumpBackward(t *testing.T) {
	// now is before LastWallClock (NTP jump backward) → wallElapsed treated as 0
	prev := state.DeviceState{
		LastSysUptime: 10000,
		LastWallClock: baseTime.Add(3600 * time.Second), // future
	}
	result, _ := DetectRebootUptime(prev, 10100, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("NTP jump backward should not produce reboot")
	}
}

func TestDetectRebootUptime_DeltaZero(t *testing.T) {
	prev := state.DeviceState{
		LastSysUptime: 5000,
		LastWallClock: baseTime.Add(-900 * time.Second),
	}
	result, _ := DetectRebootUptime(prev, 5000, baseTime, defaultDetectCfg)
	if result.IsReboot {
		t.Fatal("delta=0 should not be a reboot")
	}
}

// ---- Seed helpers ----

func TestSeedEngineState(t *testing.T) {
	prev := state.DeviceState{}
	next := SeedEngineState(prev, 3, 1000)
	if !next.EngineProbed || !next.UseEngineOIDs {
		t.Fatal("expected EngineProbed=true, UseEngineOIDs=true")
	}
	if next.LastEngineBoots != 3 || next.LastEngineTime != 1000 {
		t.Fatal("state not seeded correctly")
	}
}

func TestSeedUptimeState(t *testing.T) {
	prev := state.DeviceState{}
	next := SeedUptimeState(prev, 50000, baseTime)
	if !next.EngineProbed || next.UseEngineOIDs {
		t.Fatal("expected EngineProbed=true, UseEngineOIDs=false")
	}
	if next.LastSysUptime != 50000 {
		t.Fatal("uptime not seeded")
	}
	if !next.LastWallClock.Equal(baseTime) {
		t.Fatal("wall clock not seeded")
	}
}
