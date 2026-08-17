package metrics

import (
	"fmt"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/push"
)

// CycleMetrics holds the counters from a completed poll cycle.
type CycleMetrics struct {
	DevicesTotal int
	SuccessTotal int
	ErrorTotal   int
	RebootTotal  int
	PingSuccess  int // 0 when ping disabled
	PingFailed   int // 0 when ping disabled
	DurationSecs float64
	CompletedAt  time.Time
}

// Push sends cycle metrics to a Prometheus Pushgateway.
// If url is empty the call is a no-op (feature disabled).
func Push(url, job string, m CycleMetrics) error {
	if url == "" {
		return nil
	}

	reg := prometheus.NewRegistry()

	gauges := []struct {
		name  string
		help  string
		value float64
	}{
		{"pms_poll_devices_total", "Total devices polled this cycle", float64(m.DevicesTotal)},
		{"pms_poll_success_total", "Devices that responded successfully", float64(m.SuccessTotal)},
		{"pms_poll_error_total", "Devices that timed out or errored", float64(m.ErrorTotal)},
		{"pms_poll_reboot_total", "Reboot events detected this cycle", float64(m.RebootTotal)},
		{"pms_poll_ping_success_total", "Devices that responded to ICMP ping this cycle", float64(m.PingSuccess)},
		{"pms_poll_ping_failed_total", "Devices that did not respond to ICMP ping this cycle", float64(m.PingFailed)},
		{"pms_poll_cycle_duration_seconds", "Wall-clock cycle duration in seconds", m.DurationSecs},
		{"pms_poll_last_run_timestamp", "Unix timestamp of cycle completion", float64(m.CompletedAt.Unix())},
	}

	for _, g := range gauges {
		gauge := prometheus.NewGauge(prometheus.GaugeOpts{
			Name: g.name,
			Help: g.help,
		})
		gauge.Set(g.value)
		if err := reg.Register(gauge); err != nil {
			return fmt.Errorf("register %s: %w", g.name, err)
		}
	}

	pusher := push.New(url, job).Gatherer(reg)
	if err := pusher.Push(); err != nil {
		return fmt.Errorf("push metrics: %w", err)
	}
	return nil
}
