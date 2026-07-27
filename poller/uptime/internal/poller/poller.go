package poller

import (
	"context"
	"log/slog"
	"time"

	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/state"
)

// CycleStats summarises a completed poll cycle.
type CycleStats struct {
	Total       int
	Success     int
	Errors      int
	Reboots     int
	Duration    time.Duration
	PingSuccess int // devices that responded to ping this cycle (0 when ping disabled)
	PingFailed  int // devices that did not respond to ping this cycle (0 when ping disabled)
}

// RunPollCycle polls all devices, writes state, emits events, and logs records.
func RunPollCycle(
	ctx context.Context,
	devices []device.Device,
	store state.StateStore,
	clients Clients,
	emitter event.EventEmitter,
	pollLog event.PollLogger,
	upsert UpsertFunc,
	workerCfg WorkerConfig,
	detectCfg DetectConfig,
	maxFailures int,
	log *slog.Logger,
) CycleStats {
	start := time.Now()

	// Build jobs — load previous state for each device
	jobs := make([]PollJob, 0, len(devices))
	for _, dev := range devices {
		st, err := store.Get(dev.IP)
		if err != nil {
			log.Warn("failed to load state", "ip", dev.IP, "err", err)
		}
		jobs = append(jobs, PollJob{Device: dev, State: st})
	}

	results := runWorkers(ctx, jobs, workerCfg, clients, detectCfg, log)

	var stats CycleStats
	stats.Total = len(results)

	var upsertRows []event.UptimeRow

	for _, r := range results {
		if r.Err != nil {
			stats.Errors++
		} else {
			stats.Success++
		}
		if r.PingAttempted {
			if r.PingSucceeded {
				stats.PingSuccess++
			} else {
				stats.PingFailed++
			}
		}

		// Persist updated state
		if err := store.Put(r.Device.IP, r.NewState); err != nil {
			log.Error("failed to persist state", "ip", r.Device.IP, "err", err)
		}

		// Alert on persistent failures
		if r.NewState.ConsecutiveFailures >= maxFailures {
			log.Warn("device unreachable repeatedly",
				"ip", r.Device.IP,
				"name", r.Device.Name,
				"consecutive_failures", r.NewState.ConsecutiveFailures,
			)
		}

		// Write poll record
		if pollLog != nil {
			if err := pollLog.Write(r.Record); err != nil {
				log.Warn("poll log write failed", "ip", r.Device.IP, "err", err)
			}
		}

		// Emit reboot event
		if r.RebootEvent != nil {
			stats.Reboots++
			if err := emitter.Emit(ctx, *r.RebootEvent); err != nil {
				log.Error("emit reboot event failed", "ip", r.Device.IP, "err", err)
			}
		}

		// Collect uptime upsert rows (only successfully polled devices)
		if r.Err == nil {
			row := buildUptimeRow(r, log)
			upsertRows = append(upsertRows, row)
		}
	}

	// Batch upsert to device_uptime
	if upsert != nil && len(upsertRows) > 0 {
		upsert(ctx, upsertRows)
	}

	stats.Duration = time.Since(start)
	return stats
}

// UpsertFunc is a callback for the uptime upsert operation.
type UpsertFunc func(ctx context.Context, rows []event.UptimeRow)

// maxSysUptimeDuration is the 32-bit centisecond rollover boundary (~497 days).
const maxSysUptimeDuration = 497 * 24 * time.Hour

// maxEngineTimeDuration caps engine_time at 10 years to filter firmware garbage values.
const maxEngineTimeDuration = 10 * 365 * 24 * time.Hour

// uptimeDuration returns d if within maxDuration, else nil.
func uptimeDuration(d time.Duration, maxDuration time.Duration) *time.Duration {
	if d > maxDuration {
		return nil
	}
	return &d
}

func buildUptimeRow(r PollResult, log *slog.Logger) event.UptimeRow {
	row := event.UptimeRow{
		IP:       r.Device.IP,
		Name:     r.Device.Name,
		PolledAt: r.Record.Timestamp.Time,
	}
	if r.Device.Engine == EngineNokiaAltiplano {
		row.PollMethod = "nokia_altiplano"
		row.Uptime = uptimeDuration(time.Duration(r.NewState.LastSysUptime)*10*time.Millisecond, maxSysUptimeDuration)
	} else if r.NewState.UseEngineOIDs {
		row.PollMethod = "engine_oids"
		boots := int64(r.NewState.LastEngineBoots)
		engTime := int64(r.NewState.LastEngineTime)
		row.EngineBoots = &boots
		row.EngineTime = &engTime
		engDur := time.Duration(r.NewState.LastEngineTime) * time.Second
		if engDur > maxEngineTimeDuration {
			log.Warn("engine_time exceeds cap, uptime will be null", "ip", r.Device.IP, "engine_time_days", int(engDur.Hours()/24))
		}
		row.Uptime = uptimeDuration(engDur, maxEngineTimeDuration)
	} else {
		row.PollMethod = "sys_uptime"
		row.Uptime = uptimeDuration(time.Duration(r.NewState.LastSysUptime)*10*time.Millisecond, maxSysUptimeDuration)
	}
	up := int64(r.NewState.LastSysUptime)
	row.SysUptime = &up
	if !r.NewState.LastBootTime.IsZero() {
		t := r.NewState.LastBootTime
		row.LastReboot = &t
	}
	if r.Record.LastPingSuccessAt != nil {
		t := r.Record.LastPingSuccessAt.Time
		row.LastPingSuccessAt = &t
	}
	row.LastPingRTTMs = r.Record.LastPingRTTMs
	return row
}
