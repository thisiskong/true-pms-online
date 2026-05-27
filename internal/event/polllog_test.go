package event

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func newTestPollLogger(t *testing.T) (*FilePollLogger, string) {
	t.Helper()
	dir := t.TempDir()
	l, err := NewFilePollLogger(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	return l, dir
}

func TestPollLogger_WriteSameDay(t *testing.T) {
	l, dir := newTestPollLogger(t)
	day := time.Date(2026, 5, 27, 10, 0, 0, 0, time.UTC)
	for i := 0; i < 5; i++ {
		if err := l.Write(PollRecord{Timestamp: NewLocalTime(day), IP: "10.0.0.1", Name: "sw"}); err != nil {
			t.Fatal(err)
		}
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 1 {
		t.Fatalf("expected 1 file, got %d", len(entries))
	}
}

func TestPollLogger_DateRollover(t *testing.T) {
	l, dir := newTestPollLogger(t)
	day1 := time.Date(2026, 5, 27, 23, 59, 0, 0, time.UTC)
	day2 := time.Date(2026, 5, 28, 0, 1, 0, 0, time.UTC)
	if err := l.Write(PollRecord{Timestamp: NewLocalTime(day1), IP: "10.0.0.1"}); err != nil {
		t.Fatal(err)
	}
	if err := l.Write(PollRecord{Timestamp: NewLocalTime(day2), IP: "10.0.0.1"}); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(dir)
	if len(entries) != 2 {
		t.Fatalf("expected 2 files after rollover, got %d", len(entries))
	}
}

func TestPruneOldLogs_DeletesOldFiles(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 5, 27, 10, 0, 0, 0, time.UTC)

	// create 35 days of files
	for i := 0; i < 35; i++ {
		d := now.AddDate(0, 0, -i)
		dateStr := d.UTC().Format("2006-01-02")
		for _, prefix := range []string{"poll.", "reboot."} {
			path := filepath.Join(dir, prefix+dateStr+".log")
			_ = os.WriteFile(path, []byte("x"), 0644)
		}
	}

	PruneOldLogs(dir, dir, 30, now)

	entries, _ := os.ReadDir(dir)
	// only files within 30-day window should remain (days 0–29 = 30 files × 2 types = 60)
	// days 30–34 should be deleted (5 days × 2 = 10 files)
	if len(entries) != 60 {
		t.Fatalf("expected 60 files, got %d", len(entries))
	}
}

func TestPruneOldLogs_KeepForever(t *testing.T) {
	dir := t.TempDir()
	now := time.Date(2026, 5, 27, 10, 0, 0, 0, time.UTC)
	for i := 0; i < 5; i++ {
		d := now.AddDate(0, -i, 0)
		_ = os.WriteFile(filepath.Join(dir, "poll."+d.Format("2006-01-02")+".log"), []byte("x"), 0644)
	}
	PruneOldLogs(dir, dir, 0, now)
	entries, _ := os.ReadDir(dir)
	if len(entries) != 5 {
		t.Fatalf("expected all 5 files kept with retention=0, got %d", len(entries))
	}
}
