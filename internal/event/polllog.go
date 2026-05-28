package event

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// PollLogger writes one NDJSON record per device per cycle to a daily-rotated file.
type PollLogger interface {
	Write(record PollRecord) error
	Close() error
}

// FilePollLogger implements PollLogger with daily file rotation.
type FilePollLogger struct {
	mu       sync.Mutex
	dir      string
	file     *os.File
	openDate string
}

func NewFilePollLogger(dir string) (*FilePollLogger, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create poll log dir: %w", err)
	}
	return &FilePollLogger{dir: dir}, nil
}

func (l *FilePollLogger) Write(rec PollRecord) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if err := l.rotateIfNeeded(rec.Timestamp.Time); err != nil {
		return err
	}

	line, err := json.Marshal(rec)
	if err != nil {
		return fmt.Errorf("marshal poll record: %w", err)
	}
	line = append(line, '\n')
	_, err = l.file.Write(line)
	return err
}

func (l *FilePollLogger) Close() error {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file != nil {
		return l.file.Close()
	}
	return nil
}

func (l *FilePollLogger) rotateIfNeeded(t time.Time) error {
	today := t.UTC().Format("2006-01-02")
	if l.file != nil && l.openDate == today {
		return nil
	}
	active := filepath.Join(l.dir, "uptime.log")
	if l.file != nil {
		_ = l.file.Close()
		_ = os.Rename(active, filepath.Join(l.dir, "uptime."+l.openDate+".log"))
	} else if info, err := os.Stat(active); err == nil {
		modDate := info.ModTime().UTC().Format("2006-01-02")
		if modDate != today {
			_ = os.Rename(active, filepath.Join(l.dir, "uptime."+modDate+".log"))
		}
	}
	f, err := os.OpenFile(active, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("open poll log %s: %w", active, err)
	}
	l.file = f
	l.openDate = today
	return nil
}

// PruneOldLogs deletes poll, reboot, and app log files older than retentionDays.
// retentionDays=0 means keep forever. appLogDir is only pruned when non-empty.
func PruneOldLogs(pollDir, rebootDir, appLogDir string, retentionDays int, now time.Time) {
	if retentionDays <= 0 {
		return
	}
	cutoff := now.UTC().AddDate(0, 0, -retentionDays)
	pruneDir(pollDir, "uptime.", cutoff)
	pruneDir(rebootDir, "reboot.", cutoff)
	if appLogDir != "" {
		pruneDir(appLogDir, "poll-uptime.", cutoff)
	}
}

func pruneDir(dir, prefix string, cutoff time.Time) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		name := e.Name()
		if len(name) < len(prefix)+10 {
			continue
		}
		if name[:len(prefix)] != prefix {
			continue
		}
		// extract YYYY-MM-DD
		dateStr := name[len(prefix) : len(prefix)+10]
		t, err := time.Parse("2006-01-02", dateStr)
		if err != nil {
			continue
		}
		if t.Before(cutoff) {
			_ = os.Remove(filepath.Join(dir, name))
		}
	}
}
