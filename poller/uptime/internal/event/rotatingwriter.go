package event

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// RotatingWriter is a thread-safe io.WriteCloser that writes to
// <dir>/poll-uptime.log, rotating at UTC midnight to <dir>/poll-uptime.YYYY-MM-DD.log.
type RotatingWriter struct {
	mu       sync.Mutex
	dir      string
	file     *os.File
	openDate string
}

func NewRotatingWriter(dir string) (*RotatingWriter, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create log dir: %w", err)
	}
	return &RotatingWriter{dir: dir}, nil
}

func (w *RotatingWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if err := w.rotateIfNeeded(time.Now().UTC()); err != nil {
		return 0, err
	}
	return w.file.Write(p)
}

func (w *RotatingWriter) Close() error {
	w.mu.Lock()
	defer w.mu.Unlock()
	if w.file != nil {
		return w.file.Close()
	}
	return nil
}

func (w *RotatingWriter) rotateIfNeeded(t time.Time) error {
	today := t.UTC().Format("2006-01-02")
	if w.file != nil && w.openDate == today {
		return nil
	}
	active := filepath.Join(w.dir, "poll-uptime.log")
	if w.file != nil {
		_ = w.file.Close()
		_ = os.Rename(active, filepath.Join(w.dir, "poll-uptime."+w.openDate+".log"))
	} else if info, err := os.Stat(active); err == nil {
		modDate := info.ModTime().UTC().Format("2006-01-02")
		if modDate != today {
			_ = os.Rename(active, filepath.Join(w.dir, "poll-uptime."+modDate+".log"))
		}
	}
	f, err := os.OpenFile(active, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("open log file %s: %w", active, err)
	}
	w.file = f
	w.openDate = today
	return nil
}
