package event

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func testQueue(t *testing.T) (*RetryQueue, string) {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "retry.queue")
	return NewRetryQueue(path, slog.Default()), path
}

func makeEvent(ip string) RebootEvent {
	return RebootEvent{
		DeviceIP:        ip,
		DeviceName:      "test-" + ip,
		EstimatedBoot:   time.Now(),
		DetectedAt:      time.Now(),
		DetectionMethod: MethodSysUptime,
	}
}

func TestRetryQueue_WriteAndRead(t *testing.T) {
	q, _ := testQueue(t)
	for i := 0; i < 3; i++ {
		if err := q.Append(makeEvent("10.0.0." + string(rune('1'+i)))); err != nil {
			t.Fatal(err)
		}
	}
	var got []RebootEvent
	err := q.Drain(context.Background(), func(_ context.Context, ev RebootEvent) error {
		got = append(got, ev)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 events, got %d", len(got))
	}
}

func TestRetryQueue_DrainAllSucceed(t *testing.T) {
	q, path := testQueue(t)
	for i := 0; i < 3; i++ {
		_ = q.Append(makeEvent("10.0.0.1"))
	}
	err := q.Drain(context.Background(), func(_ context.Context, _ RebootEvent) error { return nil })
	if err != nil {
		t.Fatal(err)
	}
	if _, statErr := os.Stat(path); !os.IsNotExist(statErr) {
		t.Fatal("queue file should be deleted after full drain")
	}
}

func TestRetryQueue_PartialDrainOnFailure(t *testing.T) {
	q, path := testQueue(t)
	_ = q.Append(makeEvent("10.0.0.1"))
	_ = q.Append(makeEvent("10.0.0.2"))
	_ = q.Append(makeEvent("10.0.0.3"))

	calls := 0
	err := q.Drain(context.Background(), func(_ context.Context, _ RebootEvent) error {
		calls++
		if calls == 2 {
			return errors.New("db down")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	// events 2 and 3 should remain
	var remaining []RebootEvent
	_ = q.Drain(context.Background(), func(_ context.Context, ev RebootEvent) error {
		remaining = append(remaining, ev)
		return nil
	})
	if len(remaining) != 2 {
		t.Fatalf("expected 2 remaining, got %d", len(remaining))
	}
	_ = path
}

func TestRetryQueue_EmptyQueue(t *testing.T) {
	q, _ := testQueue(t)
	err := q.Drain(context.Background(), func(_ context.Context, _ RebootEvent) error {
		t.Fatal("should not be called on empty queue")
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestRetryQueue_CorruptEntry(t *testing.T) {
	q, path := testQueue(t)
	_ = q.Append(makeEvent("10.0.0.1"))
	// inject corrupt line
	f, _ := os.OpenFile(path, os.O_APPEND|os.O_WRONLY, 0644)
	_, _ = f.WriteString("not-json\n")
	f.Close()
	_ = q.Append(makeEvent("10.0.0.2"))

	var got []RebootEvent
	err := q.Drain(context.Background(), func(_ context.Context, ev RebootEvent) error {
		got = append(got, ev)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 {
		t.Fatalf("expected 2 valid events (corrupt line skipped), got %d", len(got))
	}
}
