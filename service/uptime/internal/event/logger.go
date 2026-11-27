package event

import (
	"context"
	"log/slog"
)

// LogEmitter writes reboot events to the structured logger (always active).
type LogEmitter struct {
	log *slog.Logger
}

func NewLogEmitter(log *slog.Logger) *LogEmitter {
	return &LogEmitter{log: log}
}

func (e *LogEmitter) Emit(_ context.Context, ev RebootEvent) error {
	e.log.Info("reboot detected",
		"ip", ev.DeviceIP,
		"name", ev.DeviceName,
		"method", ev.DetectionMethod,
		"suspected", ev.IsSuspected,
		"estimated_boot", ev.EstimatedBoot,
		"prev_value", ev.PrevValue,
		"curr_value", ev.CurrValue,
	)
	return nil
}

func (e *LogEmitter) Close() error { return nil }
