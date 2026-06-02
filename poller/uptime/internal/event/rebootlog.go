package event

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

type rebootLogEntry struct {
	Timestamp       LocalTime       `json:"timestamp"`
	IP              string          `json:"ip"`
	Name            string          `json:"name"`
	BootTime        *LocalTime      `json:"boot_time,omitempty"`
	IsSuspected     bool            `json:"is_suspected"`
	DetectionMethod DetectionMethod `json:"detection_method"`
	PrevValue       uint32          `json:"prev_value"`
	CurrValue       uint32          `json:"curr_value"`
}

// RebootLogEmitter appends reboot events to a daily-rotated NDJSON file.
type RebootLogEmitter struct {
	mu       sync.Mutex
	dir      string
	file     *os.File
	openDate string // "2006-01-02"
}

func NewRebootLogEmitter(dir string) (*RebootLogEmitter, error) {
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("create reboot log dir: %w", err)
	}
	return &RebootLogEmitter{dir: dir}, nil
}

func (e *RebootLogEmitter) Emit(_ context.Context, ev RebootEvent) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	if err := e.rotateIfNeeded(ev.DetectedAt); err != nil {
		return err
	}

	entry := rebootLogEntry{
		Timestamp:       NewLocalTime(ev.DetectedAt),
		IP:              ev.DeviceIP,
		Name:            ev.DeviceName,
		IsSuspected:     ev.IsSuspected,
		DetectionMethod: ev.DetectionMethod,
		PrevValue:       ev.PrevValue,
		CurrValue:       ev.CurrValue,
	}
	if !ev.EstimatedBoot.IsZero() {
		t := NewLocalTime(ev.EstimatedBoot)
		entry.BootTime = &t
	}

	line, err := json.Marshal(entry)
	if err != nil {
		return fmt.Errorf("marshal reboot entry: %w", err)
	}
	line = append(line, '\n')
	_, err = e.file.Write(line)
	return err
}

func (e *RebootLogEmitter) Close() error {
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.file != nil {
		return e.file.Close()
	}
	return nil
}

func (e *RebootLogEmitter) rotateIfNeeded(t time.Time) error {
	today := t.UTC().Format("2006-01-02")
	if e.file != nil && e.openDate == today {
		return nil
	}
	active := filepath.Join(e.dir, "reboot.log")
	if e.file != nil {
		_ = e.file.Close()
		_ = os.Rename(active, filepath.Join(e.dir, "reboot."+e.openDate+".log"))
	} else if info, err := os.Stat(active); err == nil {
		modDate := info.ModTime().UTC().Format("2006-01-02")
		if modDate != today {
			_ = os.Rename(active, filepath.Join(e.dir, "reboot."+modDate+".log"))
		}
	}
	f, err := os.OpenFile(active, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return fmt.Errorf("open reboot log %s: %w", active, err)
	}
	e.file = f
	e.openDate = today
	return nil
}
