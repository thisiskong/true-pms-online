package poller

import (
	"context"
	"log/slog"
	"sync"
	"time"

	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/snmp"
	"github.com/thisiskong/true-pms-online/internal/state"
)

// PollJob is a single device poll task.
type PollJob struct {
	Device device.Device
	State  state.DeviceState
}

// PollResult is the outcome of polling one device.
type PollResult struct {
	Device      device.Device
	NewState    state.DeviceState
	Record      event.PollRecord
	RebootEvent *event.RebootEvent // nil if no reboot detected
	Err         error
}

// runWorkers starts concurrency workers, feeds them jobs, and collects results.
func runWorkers(
	ctx context.Context,
	jobs []PollJob,
	cfg WorkerConfig,
	client snmp.SNMPClient,
	detectCfg DetectConfig,
	log *slog.Logger,
) []PollResult {
	jobCh := make(chan PollJob, len(jobs))
	resultCh := make(chan PollResult, len(jobs))

	var wg sync.WaitGroup
	for i := 0; i < cfg.Concurrency; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for job := range jobCh {
				resultCh <- processJob(ctx, job, cfg.SNMPTimeout, client, detectCfg, log)
			}
		}()
	}

	for _, j := range jobs {
		jobCh <- j
	}
	close(jobCh)

	go func() {
		wg.Wait()
		close(resultCh)
	}()

	results := make([]PollResult, 0, len(jobs))
	for r := range resultCh {
		results = append(results, r)
	}
	return results
}

// WorkerConfig holds pool parameters.
type WorkerConfig struct {
	Concurrency int
	SNMPTimeout time.Duration
}

func processJob(
	ctx context.Context,
	job PollJob,
	timeout time.Duration,
	client snmp.SNMPClient,
	cfg DetectConfig,
	log *slog.Logger,
) PollResult {
	now := time.Now().UTC()
	dev := job.Device
	prev := job.State

	// Per-device timeout
	devCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	gc, ok := client.(*snmp.GoSNMPClient)
	if !ok {
		return PollResult{Device: dev, NewState: prev, Err: nil,
			Record: errRecord(dev, now, "internal: client not GoSNMPClient")}
	}

	// Determine which OIDs to fetch
	if !prev.EngineProbed || (!prev.EngineProbed && prev.ReprobeAt.Before(now)) {
		return handleProbe(devCtx, gc, dev, prev, now, cfg, log)
	}

	if prev.UseEngineOIDs {
		return handlePathA(devCtx, gc, dev, prev, now, cfg, log)
	}
	return handlePathB(devCtx, gc, dev, prev, now, cfg, log)
}

func handleProbe(
	ctx context.Context,
	client *snmp.GoSNMPClient,
	dev device.Device,
	prev state.DeviceState,
	now time.Time,
	cfg DetectConfig,
	log *slog.Logger,
) PollResult {
	values, absent, err := client.GetWithAbsent(ctx, dev, snmp.ProbeOIDs)
	if err != nil {
		next := prev
		next.ConsecutiveFailures++
		rec := errRecord(dev, now, err.Error())
		return PollResult{Device: dev, NewState: next, Record: rec, Err: err}
	}

	engineAbsent := absent[snmp.OIDEngineBoots] || absent[snmp.OIDEngineTime]
	if !engineAbsent {
		boots := values[snmp.OIDEngineBoots]
		engTime := values[snmp.OIDEngineTime]
		next := SeedEngineState(prev, boots, engTime)
		next.ConsecutiveFailures = 0
		boots32 := boots
		engTime32 := engTime
		rec := event.PollRecord{
			Timestamp:   now,
			IP:          dev.IP,
			Name:        dev.Name,
			EngineBoots: &boots32,
			EngineTime:  &engTime32,
		}
		return PollResult{Device: dev, NewState: next, Record: rec}
	}

	// Path B — use sysUptime from the same probe response
	sysUptime := values[snmp.OIDSysUptime]
	next := SeedUptimeState(prev, sysUptime, now)
	next.ConsecutiveFailures = 0
	rec := event.PollRecord{
		Timestamp: now,
		IP:        dev.IP,
		Name:      dev.Name,
		SysUptime: &sysUptime,
	}
	return PollResult{Device: dev, NewState: next, Record: rec}
}

func handlePathA(
	ctx context.Context,
	client *snmp.GoSNMPClient,
	dev device.Device,
	prev state.DeviceState,
	now time.Time,
	cfg DetectConfig,
	log *slog.Logger,
) PollResult {
	values, absent, err := client.GetWithAbsent(ctx, dev, snmp.EngineOIDs)
	if err != nil {
		next := prev
		next.ConsecutiveFailures++
		return PollResult{Device: dev, NewState: next, Record: errRecord(dev, now, err.Error()), Err: err}
	}

	// Firmware downgrade — engine OIDs disappeared
	if absent[snmp.OIDEngineBoots] || absent[snmp.OIDEngineTime] {
		log.Warn("engine OIDs disappeared, switching to Path B", "ip", dev.IP)
		sysUptime := values[snmp.OIDSysUptime]
		next := prev
		next.UseEngineOIDs = false
		next.LastSysUptime = sysUptime
		next.LastWallClock = now
		next.ConsecutiveFailures = 0
		rec := event.PollRecord{Timestamp: now, IP: dev.IP, Name: dev.Name, SysUptime: &sysUptime}
		return PollResult{Device: dev, NewState: next, Record: rec}
	}

	boots := values[snmp.OIDEngineBoots]
	engTime := values[snmp.OIDEngineTime]

	result, next := DetectRebootEngine(prev, boots, engTime, now)
	next.ConsecutiveFailures = 0

	boots32 := boots
	engTime32 := engTime
	rec := event.PollRecord{
		Timestamp:       now,
		IP:              dev.IP,
		Name:            dev.Name,
		EngineBoots:     &boots32,
		EngineTime:      &engTime32,
		IsReboot:        result.IsReboot,
		DetectionMethod: result.DetectionMethod,
	}
	if result.IsReboot && !result.EstimatedBoot.IsZero() {
		t := result.EstimatedBoot
		rec.BootTime = &t
	}

	var rev *event.RebootEvent
	if result.IsReboot {
		ev := event.RebootEvent{
			DeviceIP:        dev.IP,
			DeviceName:      dev.Name,
			EstimatedBoot:   result.EstimatedBoot,
			DetectedAt:      now,
			PrevValue:       result.PrevValue,
			CurrValue:       result.CurrValue,
			IsSuspected:     false,
			DetectionMethod: result.DetectionMethod,
		}
		rev = &ev
	}
	return PollResult{Device: dev, NewState: next, Record: rec, RebootEvent: rev}
}

func handlePathB(
	ctx context.Context,
	client *snmp.GoSNMPClient,
	dev device.Device,
	prev state.DeviceState,
	now time.Time,
	cfg DetectConfig,
	log *slog.Logger,
) PollResult {
	values, _, err := client.GetWithAbsent(ctx, dev, snmp.UptimeOIDs)
	if err != nil {
		next := prev
		next.ConsecutiveFailures++
		return PollResult{Device: dev, NewState: next, Record: errRecord(dev, now, err.Error()), Err: err}
	}

	sysUptime := values[snmp.OIDSysUptime]
	result, next := DetectRebootUptime(prev, sysUptime, now, cfg)
	next.ConsecutiveFailures = 0

	rec := event.PollRecord{
		Timestamp:       now,
		IP:              dev.IP,
		Name:            dev.Name,
		SysUptime:       &sysUptime,
		IsReboot:        result.IsReboot,
		IsSuspected:     result.IsSuspected,
		DetectionMethod: result.DetectionMethod,
	}
	if result.IsReboot && !result.EstimatedBoot.IsZero() {
		t := result.EstimatedBoot
		rec.BootTime = &t
	}

	var rev *event.RebootEvent
	if result.IsReboot {
		ev := event.RebootEvent{
			DeviceIP:        dev.IP,
			DeviceName:      dev.Name,
			EstimatedBoot:   result.EstimatedBoot,
			DetectedAt:      now,
			PrevValue:       result.PrevValue,
			CurrValue:       result.CurrValue,
			IsSuspected:     result.IsSuspected,
			DetectionMethod: result.DetectionMethod,
		}
		rev = &ev
	}
	return PollResult{Device: dev, NewState: next, Record: rec, RebootEvent: rev}
}

func errRecord(dev device.Device, now time.Time, msg string) event.PollRecord {
	return event.PollRecord{
		Timestamp: now,
		IP:        dev.IP,
		Name:      dev.Name,
		Error:     msg,
	}
}
