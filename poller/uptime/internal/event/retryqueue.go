package event

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
)

type queueEntry struct {
	Event RebootEvent `json:"event"`
}

// RetryQueue is a file-based NDJSON queue for failed Postgres inserts.
type RetryQueue struct {
	path string
	log  *slog.Logger
}

func NewRetryQueue(path string, log *slog.Logger) *RetryQueue {
	return &RetryQueue{path: path, log: log}
}

// Append adds an event to the queue file.
func (q *RetryQueue) Append(ev RebootEvent) error {
	if err := os.MkdirAll(filepath.Dir(q.path), 0755); err != nil {
		return fmt.Errorf("create queue dir: %w", err)
	}
	f, err := os.OpenFile(q.path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("open queue %s: %w", q.path, err)
	}
	defer f.Close()
	line, err := json.Marshal(queueEntry{Event: ev})
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(f, "%s\n", line)
	return err
}

// Drain attempts to insert all queued events via insert.
// Stops on first insert failure (DB still down). Rewrites file with remaining events.
func (q *RetryQueue) Drain(ctx context.Context, insert func(ctx context.Context, ev RebootEvent) error) error {
	f, err := os.Open(q.path)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("open queue for drain: %w", err)
	}
	defer f.Close()

	var remaining []RebootEvent
	stopped := false

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Bytes()
		var entry queueEntry
		if err := json.Unmarshal(line, &entry); err != nil {
			q.log.Warn("skip corrupt queue entry", "err", err)
			continue
		}
		if stopped {
			remaining = append(remaining, entry.Event)
			continue
		}
		if err := insert(ctx, entry.Event); err != nil {
			q.log.Warn("retry insert failed, keeping in queue", "ip", entry.Event.DeviceIP, "err", err)
			remaining = append(remaining, entry.Event)
			stopped = true
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("scan queue: %w", err)
	}
	f.Close()

	return q.rewrite(remaining)
}

func (q *RetryQueue) rewrite(events []RebootEvent) error {
	if len(events) == 0 {
		return os.Remove(q.path)
	}
	tmp := q.path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return fmt.Errorf("create queue tmp: %w", err)
	}
	w := bufio.NewWriter(f)
	for _, ev := range events {
		line, _ := json.Marshal(queueEntry{Event: ev})
		_, _ = w.Write(line)
		_ = w.WriteByte('\n')
	}
	if err := w.Flush(); err != nil {
		f.Close()
		return err
	}
	f.Close()
	return os.Rename(tmp, q.path)
}
