package event

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const upsertUptimeSQL = `
INSERT INTO device_last_uptime
  (ip, name, sys_uptime, engine_boots, engine_time, polled_at, poll_method, last_reboot_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (ip) DO UPDATE SET
  name           = EXCLUDED.name,
  sys_uptime     = EXCLUDED.sys_uptime,
  engine_boots   = EXCLUDED.engine_boots,
  engine_time    = EXCLUDED.engine_time,
  polled_at      = EXCLUDED.polled_at,
  poll_method    = EXCLUDED.poll_method,
  last_reboot_at = EXCLUDED.last_reboot_at`

// UptimeRow holds the data for one device's uptime upsert.
type UptimeRow struct {
	IP          string
	Name        string
	SysUptime   *int64
	EngineBoots *int64
	EngineTime  *int64
	PolledAt    time.Time
	PollMethod  string // "engine_oids" | "sys_uptime"
	LastReboot  *time.Time
}

// UptimeUpsert batch-upserts poll results into device_last_uptime.
type UptimeUpsert struct {
	pool       *pgxpool.Pool
	batchSize  int
	retryFile  string
	log        *slog.Logger
}

func NewUptimeUpsert(pool *pgxpool.Pool, batchSize int, retryFile string, log *slog.Logger) *UptimeUpsert {
	return &UptimeUpsert{pool: pool, batchSize: batchSize, retryFile: retryFile, log: log}
}

// UpsertAll sends all rows to Postgres in batches.
func (u *UptimeUpsert) UpsertAll(ctx context.Context, rows []UptimeRow) {
	for i := 0; i < len(rows); i += u.batchSize {
		end := i + u.batchSize
		if end > len(rows) {
			end = len(rows)
		}
		batch := rows[i:end]
		if err := u.sendBatch(ctx, batch); err != nil {
			u.log.Warn("uptime batch failed, queuing", "err", err)
			u.appendRetry(batch)
		}
	}
}

func (u *UptimeUpsert) sendBatch(ctx context.Context, rows []UptimeRow) error {
	b := &pgx.Batch{}
	for _, r := range rows {
		b.Queue(upsertUptimeSQL,
			r.IP, r.Name,
			r.SysUptime, r.EngineBoots, r.EngineTime,
			r.PolledAt, r.PollMethod, r.LastReboot,
		)
	}
	results := u.pool.SendBatch(ctx, b)
	defer results.Close()
	for range rows {
		if _, err := results.Exec(); err != nil {
			return err
		}
	}
	return nil
}

func (u *UptimeUpsert) appendRetry(rows []UptimeRow) {
	if err := os.MkdirAll(filepath.Dir(u.retryFile), 0755); err != nil {
		u.log.Error("create retry dir", "err", err)
		return
	}
	f, err := os.OpenFile(u.retryFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		u.log.Error("open uptime retry queue", "err", err)
		return
	}
	defer f.Close()
	for _, r := range rows {
		line, _ := json.Marshal(r)
		_, _ = fmt.Fprintf(f, "%s\n", line)
	}
}

// DrainRetryQueue replays the uptime retry queue. Called at startup.
func (u *UptimeUpsert) DrainRetryQueue(ctx context.Context) {
	f, err := os.Open(u.retryFile)
	if os.IsNotExist(err) {
		return
	}
	if err != nil {
		u.log.Warn("open uptime retry queue", "err", err)
		return
	}
	defer f.Close()

	var rows []UptimeRow
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		var r UptimeRow
		if err := json.Unmarshal(scanner.Bytes(), &r); err != nil {
			u.log.Warn("skip corrupt uptime retry entry", "err", err)
			continue
		}
		rows = append(rows, r)
	}
	f.Close()

	if len(rows) == 0 {
		_ = os.Remove(u.retryFile)
		return
	}

	var failed []UptimeRow
	for i := 0; i < len(rows); i += u.batchSize {
		end := i + u.batchSize
		if end > len(rows) {
			end = len(rows)
		}
		batch := rows[i:end]
		if err := u.sendBatch(ctx, batch); err != nil {
			u.log.Warn("uptime retry batch failed", "err", err)
			failed = append(failed, batch...)
			// stop on first failure — DB still down
			failed = append(failed, rows[end:]...)
			break
		}
	}

	if len(failed) == 0 {
		_ = os.Remove(u.retryFile)
		return
	}
	tmp := u.retryFile + ".tmp"
	fw, err := os.Create(tmp)
	if err != nil {
		return
	}
	w := bufio.NewWriter(fw)
	for _, r := range failed {
		line, _ := json.Marshal(r)
		_, _ = w.Write(line)
		_ = w.WriteByte('\n')
	}
	_ = w.Flush()
	fw.Close()
	_ = os.Rename(tmp, u.retryFile)
}
