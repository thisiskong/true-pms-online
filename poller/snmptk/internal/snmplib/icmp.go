package snmplib

import (
	"time"

	"github.com/go-ping/ping"
)

func IcmpPing(target *SnmpTarget, count int, interval time.Duration, timeout time.Duration) IcmpPingResult {
	t := time.Now()
	pinger, err := ping.NewPinger(target.IP)
	if err != nil {
		return IcmpPingResult{CollectTime: JsonTime(t), Error: err.Error(), RespTime: time.Since(t).Milliseconds()}
	}
	pinger.SetPrivileged(true)
	pinger.Count = count
	pinger.Interval = interval
	pinger.Timeout = timeout
	pinger.RecordRtts = false

	// log.Printf("IcmpPing: %s, %s", target.IP, "Sent")
	err = pinger.Run() // Blocks until finished.
	if err != nil {
		return IcmpPingResult{CollectTime: JsonTime(t), Error: err.Error(), RespTime: time.Since(t).Milliseconds()}
	}
	stats := pinger.Statistics() // get send/receive/duplicate/rtt stats
	// log.Printf("IcmpPing: %s, %s", target.IP, "Recv")
	return IcmpPingResult{CollectTime: JsonTime(t), Stats: stats, RespTime: time.Since(t).Milliseconds()}
}
