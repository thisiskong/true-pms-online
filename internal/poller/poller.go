package poller

import (
	"context"
	"log/slog"
	"time"

	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/snmp"
	"github.com/thisiskong/true-pms-online/internal/state"
)

// CycleStats summarises a completed poll cycle.
type CycleStats struct {
	Total    int
	Success  int
	Errors   int
	Reboots  int
	Duration time.Duration
}

// RunPollCycle polls all devices, writes state, emits events, and logs records.
func RunPollCycle(
	ctx context.Context,
	devices []device.Device,
	store state.StateStore,
	client snmp.SNMPClient,
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

	results := runWorkers(ctx, jobs, workerCfg, client, detectCfg, log)

	var stats CycleStats
	stats.Total = len(results)

	var upsertRows []event.UptimeRow

	for _, r := range results {
		if r.Err != nil {
			stats.Errors++
		} else {
			stats.Success++
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
			row := buildUptimeRow(r)
			upsertRows = append(upsertRows, row)
		}
	}

	// Batch upsert to device_last_uptime
	if upsert != nil && len(upsertRows) > 0 {
		upsert(ctx, upsertRows)
	}

	stats.Duration = time.Since(start)
	return stats
}

// UpsertFunc is a callback for the uptime upsert operation.
type UpsertFunc func(ctx context.Context, rows []event.UptimeRow)

func buildUptimeRow(r PollResult) event.UptimeRow {
	row := event.UptimeRow{
		IP:       r.Device.IP,
		Name:     r.Device.Name,
		PolledAt: r.Record.Timestamp,
	}
	if r.NewState.UseEngineOIDs {
		row.PollMethod = "engine_oids"
		boots := int64(r.NewState.LastEngineBoots)
		engTime := int64(r.NewState.LastEngineTime)
		row.EngineBoots = &boots
		row.EngineTime = &engTime
	} else {
		row.PollMethod = "sys_uptime"
		up := int64(r.NewState.LastSysUptime)
		row.SysUptime = &up
	}
	if !r.NewState.LastBootTime.IsZero() {
		t := r.NewState.LastBootTime
		row.LastReboot = &t
	}
	return row
}
