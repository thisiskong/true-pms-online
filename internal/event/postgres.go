package event

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const insertRebootSQL = `
INSERT INTO %s
  (detected_at, ip, name, boot_time, is_suspected, detection_method, prev_value, curr_value)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`

// PostgresEmitter inserts reboot events into a Postgres table with retry-queue fallback.
type PostgresEmitter struct {
	pool    *pgxpool.Pool
	table   string
	timeout time.Duration
	queue   *RetryQueue
	log     *slog.Logger
}

func NewPostgresEmitter(pool *pgxpool.Pool, table string, timeout time.Duration, queue *RetryQueue, log *slog.Logger) *PostgresEmitter {
	return &PostgresEmitter{
		pool:    pool,
		table:   table,
		timeout: timeout,
		queue:   queue,
		log:     log,
	}
}

func (e *PostgresEmitter) Emit(ctx context.Context, ev RebootEvent) error {
	if err := e.insert(ctx, ev); err != nil {
		e.log.Warn("reboot insert failed, queuing for retry", "ip", ev.DeviceIP, "err", err)
		return e.queue.Append(ev)
	}
	return nil
}

func (e *PostgresEmitter) insert(ctx context.Context, ev RebootEvent) error {
	ctx, cancel := context.WithTimeout(ctx, e.timeout)
	defer cancel()

	var bootTime *time.Time
	if !ev.EstimatedBoot.IsZero() {
		t := ev.EstimatedBoot
		bootTime = &t
	}

	_, err := e.pool.Exec(ctx,
		fmt.Sprintf(insertRebootSQL, e.table),
		ev.DetectedAt,
		ev.DeviceIP,
		ev.DeviceName,
		bootTime,
		ev.IsSuspected,
		string(ev.DetectionMethod),
		int64(ev.PrevValue),
		int64(ev.CurrValue),
	)
	return err
}

func (e *PostgresEmitter) Close() error { return nil }

// DrainRetryQueue replays queued events into Postgres. Called at startup.
func (e *PostgresEmitter) DrainRetryQueue(ctx context.Context) error {
	return e.queue.Drain(ctx, e.insert)
}
