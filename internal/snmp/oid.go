package snmp

const (
	OIDEngineBoots = "1.3.6.1.6.3.10.2.1.2.0"
	OIDEngineTime  = "1.3.6.1.6.3.10.2.1.3.0"
	OIDSysUptime   = "1.3.6.1.2.1.1.3.0"
)

// ProbeOIDs is used on first poll to determine which path to use.
var ProbeOIDs = []string{OIDEngineBoots, OIDEngineTime, OIDSysUptime}

// EngineOIDs is used on subsequent polls for Path A devices.
var EngineOIDs = []string{OIDEngineBoots, OIDEngineTime}

// UptimeOIDs is used on subsequent polls for Path B devices.
var UptimeOIDs = []string{OIDSysUptime}
