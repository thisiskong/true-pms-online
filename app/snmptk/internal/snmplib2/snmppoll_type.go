package snmplib2

import (
	"os"
	"strings"

	"github.com/gosnmp/gosnmp"
)

type SnmpPollConfig struct {
	Setting     *AppSetting  `yaml:"setting,omitempty"`     // application setting
	SnmpPoll    *SnmpPoll    `yaml:"snmpPoll,omitempty"`    // snmp poll setting
	SnmpTargets []SnmpTarget `yaml:"snmpTargets,omitempty"` // list of snmp target
}

type SnmpPoll struct {
	PollInt            int               `yaml:"pollInt"`            // Time interval (seconds) for each polling
	IcmpCount          int               `yaml:"icmpCount"`          // Count tells pinger to stop after sending (and receiving) Count echo packets
	IcmpInterval       int               `yaml:"icmpInterval"`       // Interval (milliseconds) is the wait time between each packet send
	IcmpTimeout        int               `yaml:"icmpTimeout"`        // Timeout (milliseconds) specifies a timeout before ping exits, regardless of how many packets have been received
	SnmpOption         SnmpOption        `yaml:"snmpOption"`         // snmp options
	SnmpTargetSqlQuery string            `yaml:"snmpTargetSqlQuery"` // sql where statement when query snmp target
	SnmpRequest        []*SnmpBulkGetReq `yaml:"snmpRequest"`
	Transform          []*Transform      `yaml:"transform"`
	Output             []*PollOutput     `yaml:"output"`
	ExpiredMultiplier  int               `yaml:"expiredMultiplier"` // expired multipler for isExpired() when compute delta, default value is 2. This setting is useful for ONU PON polling as there're many missing data so we increase this multiplier to avoid expired data.
}

type SnmpBulkGetReq struct {
	Vendor []string         `yaml:"vendor"`
	Model  []string         `yaml:"model"`
	Jobs   []SnmpBulkGetJob `yaml:"jobs"`
}

type SnmpBulkGetJob struct {
	Name            string    `yaml:"name"`
	ObjType         string    `yaml:"objType"`
	RequestStrategy string    `yaml:"requestStrategy"` // snmp request strategy: "row" or "column" or "get"
	MapToObjType    string    `yaml:"mapToObjType"`    // "intf" or "ponport"
	Timeout         int       `yaml:"timeout"`         // snmp request timeout in seconds
	Retries         int       `yaml:"retries"`         // snmp retries
	ExpTime         bool      `yaml:"expTime"`         // snmp exponential timeout
	MaxReqOid       int       `yaml:"maxReqOid"`       // snmp max request oid for each request
	MaxRepetition   uint32    `yaml:"maxRepetition"`   // snmp max repetition when snmp getbulk
	Oids            []SnmpOid `yaml:"oids"`
}

type Transform struct {
	ObjType          string           `yaml:"objType"`
	TransformObjType string           `yaml:"transformObjType"` // "olt-pon-traffic" or "olt-uplink" or "olt-pon" or "onu-pon"
	Fields           []TransformField `yaml:"fields"`
}

type TransformField struct {
	Name  string  `yaml:"name"` // source field name
	Mode  string  `yaml:"mode"` // delta (default), latest
	Save  string  `yaml:"save"` // output field name
	Prev  string  `yaml:"prev"` // previous value
	Curr  string  `yaml:"curr"` // current value
	Max   *uint64 `yaml:"max"`
	Limit *uint64 `yaml:"limit"`
}

type PollOutput struct {
	Name     string            `yaml:"name"`
	ObjTypes []string          `yaml:"objTypes"`
	Format   string            `yaml:"format"` // json or csv
	Path     string            `yaml:"path"`   // path to output directory
	Fields   []PollOutputField `yaml:"fields"`
	// internal
	fp *os.File
}

type PollOutputField struct {
	Name string `yaml:"name"`
	Src  string `yaml:"src"`
}

type SnmpResult struct {
	CollectTime JsonTime
	Target      SnmpTarget
	Status      string
	SnmpVars    []SnmpVar
}

type SnmpVar struct {
	CollectTime JsonTime
	ObjType     string
	SnmpName    string
	SnmpValue   interface{}
	RowId       string // unique id for output row, use for merge multiple entries into single output record. ie. ifIndex
	RowIndex    string // snmp table index
	IfIndex     string
	IfName      string
	IfSpeed     int64
	PonPort     string
	L1sp        string
	OntId       string
}

type PollRecord struct {
	CollectTime  JsonTime // latest collect time
	ReportedTime JsonTime // collect time of previous saved value (will use this in output file), if no delta: it will be set to collectTime
	RowId        string
	Meas         int
	Fields       PollRecordField
	Values       map[string]interface{}
}

type PollRecordField struct {
	IfIndex string `json:"ifIndex,omitempty"`
	IfName  string `json:"ifName,omitempty"`
	IfSpeed int64  `json:"ifSpeed,omitempty"`
	IfOper  string `json:"ifOper,omitempty"`
	PonPort string `json:"ponPort,omitempty"`
	OntId   string `json:"ontId,omitempty"`
	L1sp    string `json:"l1sp,omitempty"`
}

type PollTable struct {
	ObjType string
	Rows    map[string]*PollRecord
}

func (config *SnmpPollConfig) mapSnmpBulkGetReq(target *SnmpTarget) *SnmpBulkGetReq {
	for _, req := range config.SnmpPoll.SnmpRequest {
		if req.isMatches(target) {
			return req
		}
	}
	return nil
}

func (config *SnmpPollConfig) getTransform(objType string) *Transform {
	for _, transform := range config.SnmpPoll.Transform {
		if objType == transform.ObjType {
			return transform
		}
	}
	return nil
}

func (field *PollOutputField) getFieldName() string {
	if field.Src != "" {
		return field.Src
	}
	return field.Name
}

func (tb *PollTable) add(snmpVar SnmpVar) {
	row, ok := tb.Rows[snmpVar.RowId]
	if !ok {
		fields := PollRecordField{
			IfIndex: snmpVar.IfIndex,
			IfName:  snmpVar.IfName,
			IfSpeed: snmpVar.IfSpeed,
			PonPort: snmpVar.PonPort,
			OntId:   snmpVar.OntId,
			L1sp:    snmpVar.L1sp,
		}
		row = &PollRecord{
			CollectTime:  snmpVar.CollectTime,
			ReportedTime: snmpVar.CollectTime,
			RowId:        snmpVar.RowId,
			Fields:       fields,
			Values:       make(map[string]interface{})}
		tb.Rows[snmpVar.RowId] = row
	}
	row.Values[snmpVar.SnmpName] = snmpVar.SnmpValue
}

func (req *SnmpBulkGetReq) isMatches(target *SnmpTarget) bool {
	for _, vandor := range req.Vendor {
		if vandor == "*" || vandor == target.Vendor {
			for _, model := range req.Model {
				if model == "*" || target.Model == model {
					return true
				}
			}
		}
	}
	return false
}

func (job *SnmpBulkGetJob) mapSnmpOid(snmpPdu *gosnmp.SnmpPDU) *SnmpOid {
	for _, snmpOid := range job.Oids {
		if strings.HasPrefix(snmpPdu.Name, snmpOid.Oid+".") {
			return &snmpOid
		}
	}
	return nil
}

func (job *SnmpBulkGetJob) getMaxRepetition(target *SnmpTarget) uint32 {
	if job.MaxRepetition > 0 {
		return job.MaxRepetition
	}
	return target.MaxRepetition
}

func (job *SnmpBulkGetJob) getNonRepeaters(target *SnmpTarget, snmpOid SnmpOid) uint8 {
	// There's special case for OLT Fiberhome onu_lastdowncase (1.3.6.1.4.1.5875.800.3.10.2.1.2)
	// We must request using nonRepeters = 1, otherwise, there's no response
	if snmpOid.Oid == ".1.3.6.1.4.1.5875.800.3.10.2.1.2" {
		return 1
	}
	return 0
}
