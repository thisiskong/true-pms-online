package snmplib2

import (
	"fmt"
	"math"
	"time"

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

type AgentInfo struct {
	name  string
	nodes []string
	cid   int
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
	IP                 string              `json:"ip"`
	Port               uint16              `json:"port"`
	Version            gosnmp.SnmpVersion  `json:"version"`
	Community          string              `json:"community"`
	Timeout            uint16              `json:"timeout"` // timeout in seconds
	Retries            int                 `json:"retries"`
	MaxRepetition      uint32              `json:"maxRepetition"`
	MaxReqOid          int                 `json:"maxReqOid"`
	ExpTime            bool                `json:"expTime"`
	IcmpCount          int                 `json:"icmpCount"`            // Count tells pinger to stop after sending (and receiving) Count echo packets
	IcmpInterval       int                 `json:"icmpInterval"`         // Interval (milliseconds) is the wait time between each packet send
	IcmpTimeout        int                 `json:"icmpTimeout"`          // Timeout (milliseconds) specifies a timeout before ping exits, regardless of how many packets have been received
	Flags              []string            `json:"flags"`                // Special Flags
	Device             string              `json:"device"`               // device.name
	Network            string              `json:"network"`              // device.network
	Topology           string              `json:"topology"`             // device.topology
	Vendor             string              `json:"vendor"`               // device.vendor
	Model              string              `json:"model"`                // device.model
	Agent              string              `json:"agent"`                // discovery.agent
	PollStatus         bool                `json:"pollStatus"`           // discovery.poll_status
	InterfacesIfIndex  map[string]*Intf    `json:"intfsByIfIndex"`       // map of Intf for poll transform data, key = ifIndex
	InterfacesIfName   map[string]*Intf    `json:"intfsByIfName"`        // map of Intf for poll transform data, key = ifName
	PonPortsIfIndex    map[string]*PonPort `json:"ponPortsByIfIndex"`    // map of PonPort for poll transform data, key = ifIndex
	PonPortsIfName     map[string]*PonPort `json:"ponPortsByIfName"`     // map of PonPort for poll transform data, key = ifName
	PonPortsName       map[string]*PonPort `json:"ponPortsByName"`       // map of PonPort for poll transform data, key = ponport
	PonPortsNokiaPonId map[string]*PonPort `json:"ponPortsByNokiaPonId"` // map of PonPort for poll transform data, key = NokiaPonId (1-8)
}

type Intf struct {
	Ifindex string `json:"ifindex"`
	Ifname  string `json:"ifname"`
	Ifalias string `json:"ifalias"`
	Ifdescr string `json:"ifdescr"`
	Iftype  string `json:"iftype"`
	Ifspeed int64  `json:"ifspeed"`
	Ifoper  string `json:"ifoper"`
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

type ODN struct {
	// select oltname, ponport, l1name, l1ratio, l1len, l2name, l2ratio, l2len from odn
	PonPort string `json:"ponport"`
	L1Name  string `json:"l1name"`
	L1Ratio *int   `json:"l1ratio"`
	L1Len   *int   `json:"l1len"`
	L2Name  string `json:"l2name"`
	L2Ratio *int   `json:"l2ratio"`
	L2Len   *int   `json:"l2len"`
}

type SnmpOption struct {
	Timeout       uint16 `yaml:"timeout"`
	Retries       int    `yaml:"retries"`
	MaxRepetition uint32 `yaml:"maxRepetition"`
	MaxReqOid     int    `yaml:"maxReqOid"`
	ExpTime       bool   `yaml:"expTime"`
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
