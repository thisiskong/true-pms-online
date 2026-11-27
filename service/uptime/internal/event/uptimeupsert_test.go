package event

import (
	"testing"
	"time"
)

func TestToInterval_NormalizesDaysFromHours(t *testing.T) {
	// Regression: 1167h44m14.842573s previously stored entirely as
	// microseconds, so Postgres printed it as "1167 hours" instead of days.
	d := 1167*time.Hour + 44*time.Minute + 14*time.Second + 842573*time.Microsecond
	got := toInterval(&d)
	if got == nil || !got.Valid {
		t.Fatal("expected a valid interval")
	}
	if got.Days != 48 {
		t.Errorf("Days = %d, want 48", got.Days)
	}
	wantMicros := (15*time.Hour + 44*time.Minute + 14*time.Second + 842573*time.Microsecond).Microseconds()
	if got.Microseconds != wantMicros {
		t.Errorf("Microseconds = %d, want %d", got.Microseconds, wantMicros)
	}
}

func TestToInterval_NilInput(t *testing.T) {
	if got := toInterval(nil); got != nil {
		t.Errorf("expected nil for nil input, got %+v", got)
	}
}

func TestToInterval_UnderOneDay(t *testing.T) {
	d := 5 * time.Hour
	got := toInterval(&d)
	if got.Days != 0 {
		t.Errorf("Days = %d, want 0", got.Days)
	}
	if got.Microseconds != d.Microseconds() {
		t.Errorf("Microseconds = %d, want %d", got.Microseconds, d.Microseconds())
	}
}
