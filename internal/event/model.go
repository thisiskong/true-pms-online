package event

import "time"

// DetectionMethod indicates which algorithm detected the reboot.
type DetectionMethod string

const (
	MethodEngineBoots DetectionMethod = "engine_boots" // Path A: snmpEngineBoots incremented
	MethodSysUptime   DetectionMethod = "sys_uptime"   // Path B: sysUptime went backwards
	MethodGapInferred DetectionMethod = "gap_inferred" // Path B: inferred from poller outage gap
)

// RebootEvent is emitted when a device reboot is detected.
type RebootEvent struct {
	DeviceIP        string
	DeviceName      string
	EstimatedBoot   time.Time
	DetectedAt      time.Time
	PrevValue       uint32          // snmpEngineBoots or sysUptime depending on DetectionMethod
	CurrValue       uint32
	IsSuspected     bool            // true only when DetectionMethod == MethodGapInferred
	DetectionMethod DetectionMethod
}

// PollRecord is written to the JSON poll log for every device polled each cycle.
type PollRecord struct {
	Timestamp       LocalTime       `json:"timestamp"`
	IP              string          `json:"ip"`
	Name            string          `json:"name"`
	SysUptime       *uint32         `json:"sys_uptime,omitempty"`
	EngineBoots     *uint32         `json:"engine_boots,omitempty"`
	EngineTime      *uint32         `json:"engine_time,omitempty"`
	Error           string          `json:"error,omitempty"`
	IsReboot        bool            `json:"is_reboot"`
	IsSuspected     bool            `json:"is_suspected,omitempty"`
	DetectionMethod DetectionMethod `json:"detection_method,omitempty"`
	BootTime        *LocalTime      `json:"boot_time,omitempty"`
	LastPingSuccessAt *LocalTime `json:"last_ping_success_at,omitempty"`
	LastPingRTTMs     *float64   `json:"last_ping_rtt_ms,omitempty"`
}
