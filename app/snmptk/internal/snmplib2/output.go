package snmplib2

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path"
	"strings"
	"time"
)

func (out *PollOutput) Contains(objType string) bool {
	for _, val := range out.ObjTypes {
		if val == objType {
			return true
		}
	}
	return false
}

func (out *PollOutput) openFile(config *SnmpPollConfig) *os.File {
	pollint := time.Duration(config.SnmpPoll.PollInt) * time.Second
	dt := time.Now().Add(-pollint).Format("20060102T1504")
	datadir := path.Join(out.Path, fmt.Sprintf("%s.%s", out.Name, out.Format))
	hostname, _ := os.Hostname()
	filename := fmt.Sprintf("%s-%s-%s.%s.tmp", out.Name, hostname, dt, out.Format)
	file := path.Join(datadir, filename)
	os.MkdirAll(path.Dir(file), os.ModePerm)
	fp, err := os.OpenFile(file, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	log.Printf("openFile: %s: %s", out.Name, fp.Name())
	out.fp = fp
	return fp
}

func (out *PollOutput) closeFile() {
	if out.fp != nil {
		out.fp.Close()
		oldpath := out.fp.Name()
		dirname, filename := path.Split(oldpath)
		newpath := path.Join(dirname, strings.Replace(filename, ".tmp", "", 1))
		log.Printf("output: %s", newpath)
		os.Rename(oldpath, newpath)
	}
}

func (tb *PollTable) writeFile(config *SnmpPollConfig, result *SnmpResult) {
	for _, out := range config.SnmpPoll.Output {
		if !out.Contains(tb.ObjType) {
			continue
		}
		// logInfo("out", tb)
		if out.Format == "json" {
			for _, row := range tb.Rows {
				obj := make(map[string]interface{})
				// obj["objType"] = tb.ObjType
				obj["collectTime"] = row.ReportedTime.Format(DateTimeFormat)
				obj["meas"] = row.Meas
				obj["ip"] = result.Target.IP
				obj["device"] = result.Target.Device
				obj["vendor"] = result.Target.Vendor
				obj["model"] = result.Target.Model

				// obj["ifindex"] = row.Fields.IfIndex
				// obj["ifname"] = row.Fields.IfName
				// obj["ponport"] = row.Fields.PonPort
				// obj["ontid"] = row.Fields.OntId
				// obj["l1sp"] = row.Fields.L1sp
				if row.Fields.IfSpeed > 0 {
					obj["ifspeed"] = row.Fields.IfSpeed
				}
				setIfNotBlank(obj, "ifindex", row.Fields.IfIndex)
				setIfNotBlank(obj, "ifname", row.Fields.IfName)
				setIfNotBlank(obj, "ifoper", row.Fields.IfOper)
				setIfNotBlank(obj, "ponport", row.Fields.PonPort)
				setIfNotBlank(obj, "ontid", row.Fields.OntId)
				setIfNotBlank(obj, "l1sp", row.Fields.L1sp)

				// // onupon
				// if row.Fields.ODN != nil {
				// 	setIfNotBlank(obj, "l1name", (*row.Fields.ODN).L1Name)
				// 	setIfNotBlank(obj, "l2name", (*row.Fields.ODN).L2Name)
				// 	setIfNotBlankInt(obj, "l1len", (*row.Fields.ODN).L1Len)
				// 	setIfNotBlankInt(obj, "l2len", (*row.Fields.ODN).L2Len)
				// 	setIfNotBlankInt(obj, "l1ratio", (*row.Fields.ODN).L1Ratio)
				// 	setIfNotBlankInt(obj, "l2ratio", (*row.Fields.ODN).L2Ratio)
				// }

				for _, field := range out.Fields {
					value, ok := row.Values[field.getFieldName()]
					if ok {
						obj[field.Name] = value
					} else {
						obj[field.Name] = nil
					}
				}
				s, _ := json.Marshal(obj)
				out.fp.Write(s)
				out.fp.WriteString("\n")

				// log.Printf("%s", s)
				// s, _ = json.MarshalIndent(obj, "", " ")
				// log.Printf("%s", s)
			}
		} else if out.Format == "tsdb" {
			for _, row := range tb.Rows {
				// TSDB: <metric> <timestamp> <value> <tagk=tagv> [<tagkN=tagvN>]
				for _, field := range out.Fields {
					value, ok := row.Values[field.getFieldName()]
					if ok {
						switch val := value.(type) {
						case uint64:
							if val > 9223372036854775807 {
								log.Printf("Error! TsdbOverflow: %s|%s|%s|%s|%v", result.Target.IP, row.Fields.IfIndex, out.Name, field.Name, value)
							} else {
								out.fp.WriteString(fmt.Sprintf("%s %d %d ip=%s intf=%s\n",
									field.Name, row.ReportedTime.Milliseconds(), value, result.Target.IP, row.Fields.IfIndex))
							}
						case float64:
							if val > 9223372036854775807 {
								log.Printf("Error! TsdbOverflow: %s|%s|%s|%s|%v", result.Target.IP, row.Fields.IfIndex, out.Name, field.Name, value)
							} else {
								out.fp.WriteString(fmt.Sprintf("%s %d %f ip=%s intf=%s\n",
									field.Name, row.ReportedTime.Milliseconds(), value, result.Target.IP, row.Fields.IfIndex))
							}
						default:
							out.fp.WriteString(fmt.Sprintf("%s %d %v ip=%s intf=%s\n",
								field.Name, row.ReportedTime.Milliseconds(), value, result.Target.IP, row.Fields.IfIndex))
						}
					}
				}
			}
		} else if out.Format == "csv" {
			for _, row := range tb.Rows {
				values := make([]string, 0)
				values = append(values, tb.ObjType)
				values = append(values, row.ReportedTime.Format(DateTimeFormat))
				values = append(values, fmt.Sprintf("%d", row.Meas))
				values = append(values, result.Target.IP)
				values = append(values, result.Target.Device)
				values = append(values, result.Target.Vendor)
				values = append(values, result.Target.Model)
				values = append(values, row.Fields.IfIndex)
				values = append(values, row.Fields.IfName)
				values = append(values, fmt.Sprintf("%d", row.Fields.IfSpeed))
				values = append(values, row.Fields.PonPort)
				values = append(values, row.Fields.OntId)
				values = append(values, row.Fields.L1sp)
				for _, field := range out.Fields {
					value, ok := row.Values[field.getFieldName()]
					if ok {
						values = append(values, fmt.Sprintf("%v", value))
					} else {
						values = append(values, "NIL")
					}
				}
				out.fp.WriteString(strings.Join(values, "|"))
				out.fp.WriteString("\n")
			}
		}
	}
}

func setIfNotBlank(row map[string]interface{}, name string, value string) {
	if value != "" {
		row[name] = value
	}
}

func setIfNotBlankInt(row map[string]interface{}, name string, value *int) {
	row[name] = value
}
