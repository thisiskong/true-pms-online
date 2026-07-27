package poller

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/nokia"
	"github.com/thisiskong/true-pms-online/internal/state"
)

func newTestNokiaClient(t *testing.T, sysUpTime, bootDatetime string) *nokia.Client {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/auth/login"):
			_, _ = w.Write([]byte(`{"accessToken":"tok"}`))
		case strings.HasSuffix(r.URL.Path, "sys-up-time"):
			_, _ = w.Write([]byte(`{"nokia-ietf-system-aug:sys-up-time":"` + sysUpTime + `"}`))
		case strings.HasSuffix(r.URL.Path, "boot-datetime"):
			_, _ = w.Write([]byte(`{"ietf-system:boot-datetime":"` + bootDatetime + `"}`))
		}
	}))
	t.Cleanup(srv.Close)
	return nokia.NewClient(nokia.Config{BaseURL: srv.URL, Timeout: 5 * time.Second, Concurrency: 5})
}

var discardLog = slog.New(slog.NewTextHandler(io.Discard, nil))

func TestProcessNokiaJob_FirstPollSeedsNoReboot(t *testing.T) {
	client := newTestNokiaClient(t, "5323663560", "2026-06-26T01:08:53+07:00")
	dev := device.Device{IP: "10.0.0.1", Name: "RET13002G00", Engine: EngineNokiaAltiplano}

	result := processNokiaJob(context.Background(), client, dev, state.DeviceState{}, baseTime, defaultDetectCfg, discardLog)

	if result.Err != nil {
		t.Fatalf("unexpected error: %v", result.Err)
	}
	if result.Record.IsReboot {
		t.Fatal("first poll should never report a reboot")
	}
	if result.RebootEvent != nil {
		t.Fatal("first poll should not emit a reboot event")
	}
	if result.NewState.LastBootTime.IsZero() {
		t.Fatal("expected LastBootTime to be seeded")
	}
	// sysUptime (5323663560) exceeds math.MaxUint32, but PollRecord.SysUptime
	// is *uint64 precisely so Nokia's non-wrapping counter isn't lost.
	if result.Record.SysUptime == nil || *result.Record.SysUptime != 5323663560 {
		t.Errorf("expected SysUptime = 5323663560, got %v", result.Record.SysUptime)
	}
}

func TestProcessNokiaJob_SameBootTimeNoReboot(t *testing.T) {
	client := newTestNokiaClient(t, "100", "2026-06-26T01:08:53+07:00")
	dev := device.Device{IP: "10.0.0.1", Name: "RET13002G00", Engine: EngineNokiaAltiplano}
	prevBoot := time.Date(2026, 6, 26, 1, 8, 53, 0, time.FixedZone("", 7*3600))
	prev := state.DeviceState{LastBootTime: prevBoot}

	result := processNokiaJob(context.Background(), client, dev, prev, baseTime, defaultDetectCfg, discardLog)

	if result.Record.IsReboot {
		t.Fatal("unchanged boot-datetime should not report a reboot")
	}
	if !result.NewState.LastBootTime.Equal(prevBoot) {
		t.Fatal("LastBootTime should remain unchanged")
	}
}

func TestProcessNokiaJob_ChangedBootTimeDetectsReboot(t *testing.T) {
	newBoot := "2026-07-27T09:00:00+07:00"
	client := newTestNokiaClient(t, "100", newBoot)
	dev := device.Device{IP: "10.0.0.1", Name: "RET13002G00", Engine: EngineNokiaAltiplano}
	oldBoot := time.Date(2026, 6, 26, 1, 8, 53, 0, time.FixedZone("", 7*3600))
	prev := state.DeviceState{LastBootTime: oldBoot}

	result := processNokiaJob(context.Background(), client, dev, prev, baseTime, defaultDetectCfg, discardLog)

	if !result.Record.IsReboot {
		t.Fatal("changed boot-datetime should report a reboot")
	}
	if result.Record.DetectionMethod != event.MethodBootDatetime {
		t.Errorf("detection_method = %q, want %q", result.Record.DetectionMethod, event.MethodBootDatetime)
	}
	if result.RebootEvent == nil {
		t.Fatal("expected a RebootEvent to be emitted")
	}
	wantBoot, _ := time.Parse(time.RFC3339, newBoot)
	if !result.RebootEvent.EstimatedBoot.Equal(wantBoot) {
		t.Errorf("EstimatedBoot = %v, want %v", result.RebootEvent.EstimatedBoot, wantBoot)
	}
	if !result.NewState.LastBootTime.Equal(wantBoot) {
		t.Error("NewState.LastBootTime should be updated to the new boot time")
	}
}
