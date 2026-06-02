package snmplib

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"strings"
	"time"

	"github.com/go-ping/ping"
	"github.com/gosnmp/gosnmp"
)

var (
	DateTimeFormat        = "2006-01-02T15:04:05"
	Uint64Max      uint64 = math.MaxUint64 //18446744073709551615
)

type AppSetting struct {
	DbConnection             string         `json:"dbConnection,omitempty" yaml:"dbConnection,omitempty"`                         // "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable"
	LevelDbBaseDir           string         `json:"levelDbBaseDir,omitempty" yaml:"levelDbBaseDir,omitempty"`                     // leveldb storage path
	MetricUrl                string         `json:"metricUrl,omitempty" yaml:"metricUrl,omitempty"`                               // promethues server url
	RateLimit                int            `json:"rateLimit,omitempty" yaml:"rateLimit,omitempty"`                               // global rate limit (per second)
	TopologyRateLimitDefault int            `json:"topologyRateLimitDefault,omitempty" yaml:"topologyRateLimitDefault,omitempty"` // topology rate limit (per second)
	TopologyRateLimit        map[string]int `json:"topologyRateLimit,omitempty" yaml:"topologyRateLimit,omitempty"`               // topology rate limit (per second)
	HostRateLimit            int            `json:"hostRateLimit,omitempty" yaml:"hostRateLimit,omitempty"`                       // host rate limit (per second)
	Zk                       Zk             `json:"zk,omitempty" yaml:"zk,omitempty"`                                             // zk connection
	Collector                Collector      `json:"collector,omitempty" yaml:"collector,omitempty"`                               // data collector
}

type Zk struct {
	Host    string `json:"host,omitempty" yaml:"host,omitempty"`       // list of zk host: <host1>:<port1>,<host2>:<por2>,<host3>:<port3>
	Timeout int    `json:"timeout,omitempty" yaml:"timeout,omitempty"` // zk connect timeout (seconds)
}

type Collector struct {
	Hosts  []string         `json:"hosts,omitempty" yaml:"hosts,omitempty"`
	Groups []CollectorGroup `json:"groups,omitempty" yaml:"groups,omitempty"`
}

type CollectorGroup struct {
	Name  string   `json:"name,omitempty" yaml:"name,omitempty"`
	Nodes []string `json:"nodes,omitempty" yaml:"nodes,omitempty"`
}

type SnmpOid struct {
	Oid      string         `json:"oid,omitempty" yaml:"oid,omitempty"`
	Name     string         `json:"name,omitempty" yaml:"name,omitempty"`
	Type     string         `json:"type,omitempty" yaml:"type,omitempty"`
	SnmpType gosnmp.Asn1BER `json:"snmpType,omitempty" yaml:"snmpType,omitempty"`
	Enum     map[int]string `json:"enum,omitempty" yaml:"enum,omitempty"`
	Syntax   string         `json:"syntax,omitempty" yaml:"syntax,omitempty"` // PhysAddress
}

type SnmpTarget struct {
	IP            string              `json:"ip"`
	Port          uint16              `json:"port"`
	Version       gosnmp.SnmpVersion  `json:"version"`
	Community     string              `json:"community"`
	Timeout       uint16              `json:"timeout"` // timeout in seconds
	Retries       int                 `json:"retries"`
	MaxRepetition uint32              `json:"maxRepetition"`
	MaxReqOid     int                 `json:"maxReqOid"`
	ExpTime       bool                `json:"expTime"`
	IcmpCount     int                 `json:"icmpCount"`    // Count tells pinger to stop after sending (and receiving) Count echo packets
	IcmpInterval  int                 `json:"icmpInterval"` // Interval (milliseconds) is the wait time between each packet send
	IcmpTimeout   int                 `json:"icmpTimeout"`  // Timeout (milliseconds) specifies a timeout before ping exits, regardless of how many packets have been received
	Flags         []string            `json:"flags"`        // Special Flags
	Device        string              `json:"device"`       // device.name
	Network       string              `json:"network"`      // device.network
	Topology      string              `json:"topology"`     // device.topology
	Sitename      string              `json:"sitename"`     // device.sitename
	Vendor        string              `json:"vendor"`       // device.vendor
	Model         string              `json:"model"`        // device.model
	Agent         string              `json:"agent"`        // discovery.agent
	PollStatus    bool                `json:"pollStatus"`   // discovery.poll_status
	Interfaces    map[string]*Intf    `json:"intfs"`        // map of Intf for poll filter
	PonPorts      map[string]*PonPort `json:"ponPorts"`     // map of PonPort for poll filter
}

type Intf struct {
	Ifindex string `json:"ifindex"`
	Ifalias string `json:"ifalias"`
	Ifdescr string `json:"ifdescr"`
	Iftype  string `json:"iftype"`
	Ifspeed int64  `json:"ifspeed"`
	Name    string `json:"name"`
	Dstname string `json:"dstname"`
	Dstport string `json:"dstport"`
	Dstsite string `json:"dstsite"`
	Dsttype string `json:"dsttype"`
}

type PonPort struct {
	Ifindex string `json:"ifindex"`
	Ifname  string `json:"ifname"`
	Ifspeed int64  `json:"ifspeed"`
	Ifoper  string `json:"ifoper"`
	PonPort string `json:"ponport"`
	L1sp    string `json:"l1sp"`
}

type SnmpVar struct {
	Oid   string      `json:"oid"`
	Name  string      `json:"name"`
	Type  string      `json:"type"`
	Value interface{} `json:"value"`
}

type SnmpPartialResult struct {
	Error     error
	Variables []gosnmp.SnmpPDU
}

type SnmpResult struct {
	CollectTime JsonTime              `json:"collectTime,omitempty"`
	Target      SnmpTarget            `json:"target,omitempty"`
	Error       string                `json:"error,omitempty"`
	RespTime    int64                 `json:"respTime,omitempty"`
	SnmpTables  map[string]*SnmpTable `json:"snmpTables,omitempty"`
	SnmpVars    *[]SnmpVar            `json:"snmpVars,omitempty"`
	IcmpPing    *IcmpPingResult       `json:"icmpPing,omitempty"`
	Discovery   *Discovery            `json:"discovery,omitempty"`
	Device      *Device               `json:"device,omitempty"`
	SaveDevice  bool                  `json:"saveDevice,omitempty"` // Indicate whether should we process Device or not. Currently we do not process Dslam device
}

type Discovery struct {
	Id          string
	IpRange     string
	LocalAddr   *string
	PollInt     *int
	PollStatus  bool
	SnmpTargets []SnmpTarget
	Communities []string
	Network     string
	Topology    string
	Agent       string
}

type IcmpPingResult struct {
	CollectTime JsonTime         `json:"collectTime,omitempty"`
	RespTime    int64            `json:"respTime,omitempty"`
	Stats       *ping.Statistics `json:"ping,omitempty"`
	Error       string           `json:"error,omitempty"`
}

type SavedValue struct {
	CollectTime time.Time
	Values      map[string]interface{}
}

type DeltaResult struct {
	// SnmpTarget *SnmpTarget  `json:"snmpTarget"`
	IP       string       `json:"ip"`
	Hostname string       `json:"hostname"`
	Entries  []DeltaEntry `json:"entries"`
}

type DeltaEntry struct {
	CollectTime JsonTime               `json:"collectTime"`
	Meas        int                    `json:"meas"`
	Key         string                 `json:"key"`     // {ip}-{ifIndex}
	IfIndex     string                 `json:"ifIndex"` // {ifIndex}
	Values      map[string]*DeltaValue `json:"values"`
}

type DeltaValue struct {
	Name   string      `json:"name"`
	Status string      `json:"status"`
	Value1 interface{} `json:"value1"`
	Value2 interface{} `json:"value2"`
	Delta  interface{} `json:"delta"`
}

func (snmpOid *SnmpOid) GetSnmpType() gosnmp.Asn1BER {
	switch snmpOid.Type {
	case "TimeTicks":
		return gosnmp.TimeTicks
	case "Integer":
		return gosnmp.Integer
	case "Uinteger32":
		return gosnmp.Uinteger32
	case "Gauge32":
		return gosnmp.Gauge32
	case "Counter32":
		return gosnmp.Counter32
	case "Counter64":
		return gosnmp.Counter64
	case "OctetString", "ObjectIdentifier":
		return gosnmp.OctetString
	case "IPAddress":
		return gosnmp.IPAddress
	default:
		log.Fatalf("Not Support SnmpType: " + snmpOid.Type)
		return gosnmp.UnknownType
	}
}

// ---------------------------------

type SnmpOption struct {
	Timeout       uint16 `yaml:"timeout"`
	Retries       int    `yaml:"retries"`
	MaxRepetition uint32 `yaml:"maxRepetition"`
	MaxReqOid     int    `yaml:"maxReqOid"`
	ExpTime       bool   `yaml:"expTime"`
}

type DiscoveryConfig struct {
	Setting   *AppSetting    `yaml:"setting,omitempty"`   // application setting
	Discovery *DiscoveryTask `yaml:"discovery,omitempty"` // discovery setting
}

type PollTrafficConfig struct {
	Setting     *AppSetting      `yaml:"setting,omitempty"`     // application setting
	PollTraffic *PollTrafficTask `yaml:"pollTraffic,omitempty"` // poll traffic setting
	SnmpTargets []SnmpTarget     `yaml:"snmpTargets"`           // list of snmp target
}

type PollTrafficTask struct {
	IcmpCount       int             `yaml:"icmpCount"`       // Count tells pinger to stop after sending (and receiving) Count echo packets
	IcmpInterval    int             `yaml:"icmpInterval"`    // Interval (milliseconds) is the wait time between each packet send
	IcmpTimeout     int             `yaml:"icmpTimeout"`     // Timeout (milliseconds) specifies a timeout before ping exits, regardless of how many packets have been received
	SnmpOption      SnmpOption      `yaml:"snmpOption"`      // snmp options
	GetSelectedIntf bool            `yaml:"getSelectedIntf"` // true = get only enable interfaces, false = getbulk entire table
	ZteInErrors     bool            `yaml:"zteInErrors"`     // true: enable zteIfTable polling, false disable zteIfTable polling
	ZteInErrorsMode string          `yaml:"zteInErrorsMode"` // none: set to None if not found, default: set to standard ifTable if not found
	TraceIpAddrs    []string        `yaml:"traceIpAddrs"`    // list of ipaddr to write trace log
	IfTable         SnmpTableConfig `yaml:"ifTable"`         // ifTable
	ZteIfTable      SnmpTableConfig `yaml:"zteIfTable"`      // ZteIfTable for CRC Error
	Delta           *[]DeltaConfig  `yaml:"delta"`           // delta config
	// GetOid          *GetOidTask     `yaml:"getOid,omitempty"` // not use
}

type SnmpTableConfig struct {
	Name          string           `yaml:"name"`
	TableOid      string           `yaml:"tableOid"`
	NumEntriesOid string           `yaml:"numEntriesOid"`
	Indexes       []SnmpTableIndex `yaml:"indexes"`
	Columns       []SnmpOid        `yaml:"columns"`
}

type SnmpTableIndex struct {
	Name string `yaml:"name"`
}

// type GetOidTask struct {
// 	SnmpOption SnmpOption `yaml:"snmpOption"`
// 	Oids       []SnmpOid  `yaml:"oids"`
// }

type DiscoveryTask struct {
	ServiceApi       ServiceApi                 `yaml:"serviceApi"` // service endpoint for service-api
	Discoveries      []Discovery                `yaml:"discoveries"`
	IcmpCount        int                        `yaml:"icmpCount"`    // Count tells pinger to stop after sending (and receiving) Count echo packets
	IcmpInterval     int                        `yaml:"icmpInterval"` // Interval (milliseconds) is the wait time between each packet send
	IcmpTimeout      int                        `yaml:"icmpTimeout"`  // Timeout (milliseconds) specifies a timeout before ping exits, regardless of how many packets have been received
	SnmpOption       SnmpOption                 `yaml:"snmpOption"`
	SnmpOids         []SnmpOid                  `yaml:"snmpOids"`
	IfTable          SnmpTableConfig            `yaml:"ifTable"`
	IpAddrTable      SnmpTableConfig            `yaml:"ipAddrTable"`
	LldpLocPortTable SnmpTableConfig            `yaml:"lldpLocPortTable"`
	LldpRemTable     SnmpTableConfig            `yaml:"lldpRemTable"`
	ExtSnmpOids      map[string][]SnmpOid       `yaml:"extSnmpOids"`   // vendor specific oids
	ExtSnmpTables    map[string]SnmpTableConfig `yaml:"extSnmpTables"` // vendor specific tables
}

type ServiceApi struct {
	Endpoint string `yaml:"endpoint"` // service endpoint
	Timeout  int    `yaml:"timeout"`  // timeout in seconds
}

type DeltaConfig struct {
	Name  string  `yaml:"name"`
	Mode  string  `yaml:"mode"` // delta (default), latest
	Max   *uint64 `yaml:"max"`
	Limit *uint64 `yaml:"limit"`
}

// ---------------------------------

type SnmpTableEntry struct {
	Index  string              `json:"index"`
	Values map[string]*SnmpVar `json:"values"`
}

type SnmpTable struct {
	Name    string           `json:"name,omitempty"`
	Error   string           `json:"error,omitempty"`
	Entries []SnmpTableEntry `json:"entries,omitempty"`
}

func (row *SnmpTableEntry) GetValue(name string) string {
	val, ok := row.Values[name]
	if ok {
		if v, ok := val.Value.(string); ok {
			return strings.TrimSpace(v)
		}
	}
	return ""
}

func (row *SnmpTableEntry) GetValueDefault(name string, defaultValue string) string {
	val, ok := row.Values[name]
	if ok {
		if v, ok := val.Value.(string); ok {
			return strings.TrimSpace(v)
		}
	}
	return defaultValue
}

func (task *SnmpTableConfig) GetColumnOids() []string {
	oids := make([]string, 0, len(task.Columns))
	for _, snmpOid := range task.Columns {
		oids = append(oids, snmpOid.Oid)
	}
	return oids
}

func (task *SnmpTableConfig) GetColumnOidMap() *map[string]SnmpOid {
	oid_map := make(map[string]SnmpOid)
	for _, snmpOid := range task.Columns {
		oid_map[snmpOid.Oid] = snmpOid
	}
	return &oid_map
}

func (task *DiscoveryTask) GetOidList(target SnmpTarget) []string {
	oids := make([]string, 0, len(task.SnmpOids))
	for _, snmpOid := range task.SnmpOids {
		oids = append(oids, snmpOid.Oid)
	}

	// // vendor specific oids, key = target.Network
	// snmpOids, ok := task.ExtSnmpOids[target.Network]
	// if ok {
	// 	for _, snmpOid := range snmpOids {
	// 		oids = append(oids, snmpOid.Oid)
	// 	}
	// }
	return oids
}

func (task *DiscoveryTask) GetExtOidList(target SnmpTarget) []string {
	oids := make([]string, 0, len(task.SnmpOids))
	// for _, snmpOid := range task.SnmpOids {
	// 	oids = append(oids, snmpOid.Oid)
	// }

	// extSnmpOids["Default"]
	snmpOids, ok := task.ExtSnmpOids["Default"]
	if ok {
		for _, snmpOid := range snmpOids {
			oids = append(oids, snmpOid.Oid)
		}
	}

	// vendor specific oids, key = target.Network
	snmpOids, ok = task.ExtSnmpOids[target.Network]
	if ok {
		for _, snmpOid := range snmpOids {
			oids = append(oids, snmpOid.Oid)
		}
	}
	return oids
}

func (task *DiscoveryTask) GetOidMap(target SnmpTarget) *map[string]SnmpOid {
	oid_map := make(map[string]SnmpOid)
	for _, snmpOid := range task.SnmpOids {
		oid_map[snmpOid.Oid] = snmpOid
	}

	// extSnmpOids["Default"]
	snmpOids, ok := task.ExtSnmpOids["Default"]
	if ok {
		for _, snmpOid := range snmpOids {
			oid_map[snmpOid.Oid] = snmpOid
		}
	}

	// vendor specific oids, key = target.Network
	snmpOids, ok = task.ExtSnmpOids[target.Network]
	if ok {
		for _, snmpOid := range snmpOids {
			oid_map[snmpOid.Oid] = snmpOid
		}
	}
	return &oid_map
}

type JsonTime time.Time

func (t JsonTime) MarshalJSON() ([]byte, error) {
	stamp := fmt.Sprintf("\"%s\"", time.Time(t).Format(DateTimeFormat))
	return []byte(stamp), nil
}

func (t JsonTime) Format(format string) string {
	return time.Time(t).Format(format)
}

func (t JsonTime) Milliseconds() int64 {
	return time.Time(t).Round(time.Millisecond).UnixNano() / 1e6
}

func (ret IcmpPingResult) IsReachable() bool {
	if ret.Error == "" && ret.Stats.PacketsRecv > 0 {
		return true
	}
	return false
}

func (ret IcmpPingResult) ErrMsg() string {
	if ret.Error != "" {
		return ret.Error
	}
	if !ret.IsReachable() {
		return "Icmp Unreachable"
	}
	return ""
}

func (target SnmpTarget) IsZte_6180H() bool {
	return target.Vendor == "ZTE" && target.Model == "ZXCTN 6180H-A"
}

func (target SnmpTarget) IsA10_TH14045() bool {
	return (target.Vendor == "A10" && target.Model == "TH14045")
}

func (target SnmpTarget) HasFlag_RetryOnNoInstance() bool {
	for _, flag := range target.Flags {
		if flag == "RetryOnNoInstance" {
			return true
		}
	}
	return false
}

func (tb *SnmpTable) LogCsv(filename string, names []string) error {
	fout, err := os.OpenFile(filename, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
	if err != nil {
		return err
	}
	defer fout.Close()

	// header
	values := make([]string, len(names))
	values = append(values, names...)
	fout.WriteString(strings.Join(values, "|") + "\n")

	// error
	if tb.Error != "" {
		fout.WriteString(fmt.Sprintf("Error: %v", tb.Error) + "\n")
	}

	// content
	for _, row := range tb.Entries {
		values := make([]string, len(names))
		for _, name := range names {
			val, ok := row.Values[name]
			if ok {
				values = append(values, fmt.Sprintf("%s", val.Value))
			} else {
				values = append(values, "NIL")
			}
		}
		fout.WriteString(strings.Join(values, "") + "\n")
	}
	return nil
}

func (tb *SnmpTable) ToJson() string {
	s, _ := json.MarshalIndent(tb, "", " ")
	return string(s)
}
