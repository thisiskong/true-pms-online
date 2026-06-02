package snmplib

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

var DEBUG_IP_LIST map[string]bool

func NewSnmpGetProcessor(task *PollTrafficConfig, polltype string, deltafile string, tsdbfile string, datalakefile string,
	offlinedir string, pollint int, wg *sync.WaitGroup, db *DeltaDB, tasksDone chan SnmpResult, size int) {

	start := time.Now()
	defer wg.Done()

	traceIpAddrs := make(map[string]bool, len(task.PollTraffic.TraceIpAddrs))
	for _, s := range task.PollTraffic.TraceIpAddrs {
		traceIpAddrs[s] = true
	}

	hostname, _ := os.Hostname()

	// output file
	var deltajson *os.File
	var tsdb *os.File
	var dlfile *os.File
	var offlinefile *os.File

	if deltafile != "" {
		var err error
		tmpfile := fmt.Sprintf("%s.tmp", deltafile)
		// ensure parent dir exist
		parentdir := path.Dir(deltafile)
		os.MkdirAll(parentdir, os.ModePerm)
		deltajson, err = os.OpenFile(tmpfile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Fatalf("Error! Can't create delta file: %v", err)
		}
		defer closeAndRename(deltajson, tmpfile, deltafile)
	}

	if tsdbfile != "" {
		var err error
		tmpfile := fmt.Sprintf("%s.tmp", tsdbfile)
		// ensure parent dir exist
		parentdir := path.Dir(tsdbfile)
		os.MkdirAll(parentdir, os.ModePerm)
		tsdb, err = os.OpenFile(tmpfile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Printf("Error! Can't create tsdb file: %v", err)
		}
		defer closeAndRename(tsdb, tmpfile, tsdbfile)
	}

	if datalakefile != "" {
		var err error
		tmpfile := fmt.Sprintf("%s.tmp", datalakefile)
		// ensure parent dir exist
		parentdir := path.Dir(datalakefile)
		os.MkdirAll(parentdir, os.ModePerm)
		dlfile, err = os.OpenFile(tmpfile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Printf("Error! Can't create datalake file: %v", err)
		}
		defer closeAndRename(dlfile, tmpfile, datalakefile)
	}

	// offlinedir = directory: /data/traffic5m-offline.json
	if offlinedir != "" {
		var err error
		pollint_minutes := pollint / 60
		roundTime := RoundDownTime(time.Now(), pollint_minutes)

		// turn on only at 15m or 60m
		if (roundTime.Minute()%15) == 0 || (roundTime.Minute()%60) == 0 {
			tstamp := roundTime.Format("20060102T1504") // %Y%m%dT%H%M
			filename := fmt.Sprintf("%s-offline-%s-%s.json", polltype, hostname, tstamp)
			outfile := filepath.Join(offlinedir, filename)
			tmpfile := fmt.Sprintf("%s.tmp", outfile)
			// ensure parent dir exist
			parentdir := path.Dir(outfile)
			os.MkdirAll(parentdir, os.ModePerm)
			offlinefile, err = os.OpenFile(tmpfile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
			if err != nil {
				log.Printf("Error! Can't create deviceOffline file: %v", err)
			}
			defer closeAndRename(offlinefile, tmpfile, outfile)
		}
	}

	// metric
	metrics := make(map[IfTableMetricGroup]*IfTableMetric)
	pollStatusMap := make(map[string]*PollStatus) // key = network
	pollStatusErr := make([]PollStatusErr, 0, 100)

	cnt_ok := 0
	cnt_err := 0
	cnt_intf := 0
	for i := 0; i < size; i++ {
		snmpResult, ok := <-tasksDone
		if !ok {
			// channel was closed
			log.Fatal("Error: channel is closed")
		}

		metric := getOrCreateMetric(metrics, polltype, snmpResult.Target, hostname)
		pollStatus := getOrCreatePollStatus(pollStatusMap, start, polltype, snmpResult.Target.Network, hostname)

		if snmpResult.Error != "" {
			cnt_err += 1
			metric.DeviceError.Inc()
			pollStatus.Error += 1

			// offline record
			if offlinefile != nil {
				roundCollectTime := time.UnixMilli((snmpResult.CollectTime.Milliseconds() / int64(pollint*1000)) * int64(pollint*1000))
				rec := OfflineRecord{
					CollectTime: JsonTime(roundCollectTime),
					Ip:          snmpResult.Target.IP,
					Device:      snmpResult.Target.Device,
					Sitename:    snmpResult.Target.Sitename,
				}
				rec.WriteOfflineRecordAsJson(offlinefile)
			}
			pollStatusErr = addPollStatusErr(pollStatusErr, polltype, hostname, snmpResult, snmpResult.Error)

		} else {
			// ifTable
			ifTable, ok := snmpResult.SnmpTables["ifTable"]
			if !ok {
				cnt_err += 1
				metric.DeviceError.Inc()
				pollStatus.Error += 1
				pollStatusErr = addPollStatusErr(pollStatusErr, polltype, hostname, snmpResult, "ifTableNotFound")

			} else {

				if ifTable.Error == "" {
					cnt_ok += 1
					cnt_intf += len(ifTable.Entries)
					metric.DeviceSuccess.Inc()
					metric.IntfCnt.Add(float64(len(ifTable.Entries)))
					pollStatus.Success += 1

					zteIfTable := snmpResult.SnmpTables["zteIfTable"]
					pollData := mergePollData(task.PollTraffic, &snmpResult.Target, ifTable, zteIfTable)

					// debug trace
					if traceIpAddrs[snmpResult.Target.IP] {
						writeTraceLog(task, snmpResult, ifTable, zteIfTable)
					}

					// compute delta
					if task.PollTraffic.Delta != nil {
						delta := save(db, task.PollTraffic.Delta, pollint, &snmpResult.Target, snmpResult.CollectTime, pollData, metric)
						if delta != nil {
							// s, _ := json.MarshalIndent(delta, "", " ")
							// log.Printf("%v", string(s))
							writeDelta(deltajson, tsdb, dlfile, pollint, snmpResult.Target, delta)
						}
					}
				} else {
					cnt_err += 1
					metric.DeviceError.Inc()
					pollStatus.Error += 1
					pollStatusErr = addPollStatusErr(pollStatusErr, polltype, hostname, snmpResult, ifTable.Error)
				}
			}
		}
		metric.RespTime.Observe(float64(snmpResult.RespTime) / 1000)
	}

	// push metric
	PushSnmpIfTableMetric(task.Setting, metrics)

	// save pollstatus
	savePollStatus(task.Setting.DbConnection, pollStatusMap, pollStatusErr, cnt_ok, cnt_err)
	log.Printf("Completed: %d total, %d success, %d error in %s", size, cnt_ok, cnt_err, time.Since(start))
}

func writeTraceLog(task *PollTrafficConfig, snmpResult SnmpResult, ifTable *SnmpTable, zteIfTable *SnmpTable) error {
	// ifTable
	ptime := snmpResult.CollectTime.Format("20060102T1504")
	filename1 := filepath.Join(os.Getenv("HOME"), "logs", fmt.Sprintf("trace-ifTable-%s-%s.json", snmpResult.Target.IP, ptime))
	fout1, err := os.OpenFile(filename1, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
	if err != nil {
		log.Printf("Error! %v", err)
		return err
	}
	defer fout1.Close()

	// ifTable
	s, _ := json.MarshalIndent(ifTable.Entries, "", " ")
	fout1.WriteString(string(s))
	// for _, row := range ifTable.Entries {
	// 	// ifHighSpeed := row.Values["IfHighSpeed"].Value
	// 	ifOperStatus := row.Values["ifOperStatus"].Value
	// 	ifHCInOctets := row.Values["ifHCInOctets"].Value
	// 	ifHCOutOctets := row.Values["ifHCOutOctets"].Value
	// 	ifInErrors := row.Values["ifInErrors"].Value
	// 	line := fmt.Sprintf("%s|%s|%s|%v|%v|%v|%v", ptime, snmpResult.Target.IP, row.Index, ifOperStatus, ifHCInOctets, ifHCOutOctets, ifInErrors)
	// 	fout1.WriteString(line + "\n")
	// }

	// zteIfTable
	if task.PollTraffic.ZteInErrors && snmpResult.Target.IsZte_6180H() {
		filename2 := filepath.Join(os.Getenv("HOME"), "logs", fmt.Sprintf("trace-zteIfTable-%s-%s.json", snmpResult.Target.IP, ptime))
		fout2, err := os.OpenFile(filename2, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Printf("Error! %v", err)
			return err
		}
		defer fout2.Close()

		if zteIfTable != nil {
			s, _ := json.MarshalIndent(zteIfTable, "", " ")
			fout2.WriteString(string(s))
			// for _, row := range zteIfTable.Entries {
			// 	ifInErrors := row.Values["ifInErrors"].Value
			// 	line := fmt.Sprintf("%s|%s|%s|%v", ptime, snmpResult.Target.IP, row.Index, ifInErrors)
			// 	fout2.WriteString(line + "\n")
			// }
		}
	}
	return nil
}

// func writeDatalake(datalakefile *os.File, pollint int, snmpTarget SnmpTarget, delta *DeltaResult) {
// 	for _, row := range delta.Entries {
// 		ifIndex := row.Values["ifIndex"]
// 		ifHighSpeed := row.Values["ifHighSpeed"]
// 		ifHCInOctets := row.Values["ifHCInOctets"]
// 		ifHCOutOctets := row.Values["ifHCOutOctets"]
// 		ifOperStatus := row.Values["ifOperStatus"]
// 		ifInErrors := row.Values["ifInErrors"]

// 		if ifIndex == nil {
// 			// some device return inconsistent records of ifTable, drop invalid record
// 			log.Printf("Error! %v|ifIndexIsNull", snmpTarget.IP)
// 			continue
// 		}
// 		ifindex := fmt.Sprintf("%d", ifIndex.Value2.(int64))
// 		intf, ok := snmpTarget.Interfaces[ifindex]
// 		if !ok {
// 			intf = &Intf{}
// 		}

// 		roundCollectTime := JsonTime(time.UnixMilli((row.CollectTime.Milliseconds() / int64(pollint*1000)) * int64(pollint*1000)))
// 		dl := DatalakeRecord{
// 			CollectTime: roundCollectTime,
// 			Ip:          delta.IP,
// 			Ifindex:     ifindex,
// 			Meas:        int64(row.Meas),
// 			Device:      snmpTarget.Hostname,
// 			Name:        intf.name,
// 			Ifname:      intf.ifname,
// 			Ifalias:     intf.ifalias,
// 			Ifdescr:     intf.ifdescr,
// 			Iftype:      intf.iftype,
// 			Dstname:     intf.dstname,
// 			Dstport:     intf.dstport,
// 			Dstsite:     intf.dstsite,
// 			Dsttype:     intf.dsttype,
// 			Network:     snmpTarget.Network,
// 			Topology:    snmpTarget.Topology,
// 		}
// 	}
// }

func writeDelta(deltafile *os.File, tsdbfile *os.File, dlfile *os.File, pollint int, target SnmpTarget, delta *DeltaResult) {
	for _, row := range delta.Entries {
		// ifIndex := row.Values["ifIndex"]
		// ifHighSpeed := row.Values["ifHighSpeed"]
		ifHCInOctets := row.Values["ifHCInOctets"]
		ifHCOutOctets := row.Values["ifHCOutOctets"]
		ifOperStatus := row.Values["ifOperStatus"]
		ifInErrors := row.Values["ifInErrors"]

		if row.IfIndex == "" {
			// some device return inconsistent records of ifTable, drop invalid record
			log.Printf("Error! %v|ifIndexIsNull", target.IP)
			continue
		}
		// ifindex := fmt.Sprintf("%d", ifIndex.Value2.(int64))

		intf, ok := target.Interfaces[row.IfIndex]
		if !ok {
			log.Printf("Error! ip=%s, ifindex=%s, IntfNotFound", target.IP, row.IfIndex)
			continue
		}

		roundCollectTime := time.UnixMilli((row.CollectTime.Milliseconds() / int64(pollint*1000)) * int64(pollint*1000))
		meas := int64(row.Meas)
		rec := JsonRecord{
			CollectTime: JsonTime(roundCollectTime),
			Ip:          delta.IP,
			Ifindex:     row.IfIndex,
			Meas:        meas,
		}
		dl := DatalakeRecord{
			CollectTime: roundCollectTime.Format("2006-01-02 15:04:05"),
			Ip:          delta.IP,
			Device:      target.Device,
			Name:        intf.Name,
			Ifindex:     intf.Ifindex,
			Ifalias:     intf.Ifalias,
			Ifdescr:     intf.Ifdescr,
			Iftype:      intf.Iftype,
			Ifspeed:     intf.Ifspeed,
			Dstname:     intf.Dstname,
			Dstport:     intf.Dstport,
			Dstsite:     intf.Dstsite,
			Dsttype:     intf.Dsttype,
			Network:     target.Network,
			Topology:    target.Topology,
			Meas:        meas,
		}

		if ifOperStatus != nil {
			rec.Ifoper = ifOperStatus.Delta.(string)
		}
		if row.Meas > 0 {
			if ifHCInOctets != nil {
				in_octets1 := ifHCInOctets.Value1.(uint64)
				in_octets2 := ifHCInOctets.Value2.(uint64)
				in_octets := ifHCInOctets.Delta.(uint64)

				rec.In_octets1 = &in_octets1
				rec.In_octets2 = &in_octets2
				rec.In_octets = &in_octets
				rec.In_flg = ifHCInOctets.Status

				if ifHCInOctets.Delta.(uint64) > 9223372036854775807 {
					rec.in_octets_tsdb_overflow = true
				}
			}
			if ifHCOutOctets != nil {
				out_octets1 := ifHCOutOctets.Value1.(uint64)
				out_octets2 := ifHCOutOctets.Value2.(uint64)
				out_octets := ifHCOutOctets.Delta.(uint64)

				rec.Out_octets1 = &out_octets1
				rec.Out_octets2 = &out_octets2
				rec.Out_octets = &out_octets
				rec.Out_flg = ifHCOutOctets.Status

				if ifHCOutOctets.Delta.(uint64) > 9223372036854775807 {
					rec.out_octets_tsdb_overflow = true
				}
			}
			// if ifHighSpeed != nil {
			// 	// speed (convert from Mbps to bit-per-sec)
			// 	// rec.Ifspeed = int64(ifHighSpeed.Value2.(uint64) * 1000000)
			// }

			// ifspeed in bit-per-sec
			rec.Ifspeed = intf.Ifspeed
			if rec.Ifspeed > 0 {
				if ifHCInOctets != nil {
					// rate in bit-per-sec
					rate := int64(ifHCInOctets.Delta.(uint64) / uint64(row.Meas) * 8)
					bw := (float64(rate) / float64(rec.Ifspeed)) * 100
					rec.In_rate = &rate
					rec.In_bw = &bw

					// rate in gbps
					in_rate_gbps := float64(rate / 1000000000)
					dl.In_rate_gpbs = &in_rate_gbps
					dl.In_mean_bw_percent = &bw
				}
				if ifHCOutOctets != nil {
					// rate in bit-per-sec
					rate := int64(ifHCOutOctets.Delta.(uint64) / uint64(row.Meas) * 8)
					bw := (float64(rate) / float64(rec.Ifspeed)) * 100
					rec.Out_rate = &rate
					rec.Out_bw = &bw

					// rate in gbps
					out_rate_gbps := float64(rate / 1000000000)
					dl.Out_rate_gbps = &out_rate_gbps
					dl.Out_mean_bw_percent = &bw
				}
			}

			if ifInErrors != nil {
				in_err1 := ifInErrors.Value1
				in_err2 := ifInErrors.Value2
				in_err := ifInErrors.Delta

				rec.In_err1 = &in_err1
				rec.In_err2 = &in_err2
				rec.In_err = &in_err

				switch v := in_err.(type) {
				case int32:
					val := int64(v)
					dl.In_crcerr = &val
				case int64:
					val := int64(v)
					dl.In_crcerr = &val
				case uint32:
					val := int64(v)
					dl.In_crcerr = &val
				case uint64:
					val := int64(v)
					dl.In_crcerr = &val
				}

				switch v := in_err2.(type) {
				case int32:
					val := int64(v)
					dl.In_crcerr_acc = &val
				case int64:
					val := int64(v)
					dl.In_crcerr_acc = &val
				case uint32:
					val := int64(v)
					dl.In_crcerr_acc = &val
				case uint64:
					val := int64(v)
					dl.In_crcerr_acc = &val
				}
			}
		}

		// CSV file
		// err := rec.WriteCsv(deltafile)
		// if err != nil {
		// 	log.Printf("Error! write csv %v", err)
		// }

		// json file
		err := rec.WriteJson(deltafile)
		if err != nil {
			log.Printf("Error! write json %v", err)
		}

		// tsdb file
		if tsdbfile != nil {
			err = rec.WriteTsdb(tsdbfile)
			if err != nil {
				log.Printf("Error! write tsdb %v", err)
			}
		}

		// datalake file
		if dlfile != nil {
			err = dl.WriteJson(dlfile)
			if err != nil {
				log.Printf("Error! write datalake %v", err)
			}
		}
	}
}

func closeAndRename(file *os.File, oldfile string, newfile string) {
	err := file.Close()
	if err != nil {
		log.Printf("Error! %v", err)
	}
	err = os.Rename(oldfile, newfile)
	if err != nil {
		log.Printf("Error! %v", err)
	}
}

func getOrCreateMetric(metrics map[IfTableMetricGroup]*IfTableMetric, polltype string, target SnmpTarget, agent string) *IfTableMetric {
	key := IfTableMetricGroup{
		PollType: polltype,
		Agent:    agent,
		Network:  target.Network,
	}
	val, ok := metrics[key]
	if ok {
		return val
	} else {
		val = NewSnmpIfTableMetric()
		metrics[key] = val
		return val
	}
}

func getOrCreatePollStatus(pollStatusMap map[string]*PollStatus, start time.Time, polltype string, network string, agent string) *PollStatus {
	val, ok := pollStatusMap[network]
	if ok {
		return val
	} else {
		val = &PollStatus{Start: JsonTime(start), PollType: polltype, Network: network, Agent: agent, Success: 0, Error: 0}
		pollStatusMap[network] = val
		return val
	}
}

func addPollStatusErr(pollStatusErr []PollStatusErr, polltype string, hostname string, snmpResult SnmpResult, errmsg string) []PollStatusErr {
	// normalize errmsg
	// error establishing connection to host: dial udp :0->10.85.88.11:161: i/o timeout
	// error reading from socket: read udp 10.50.238.81:49888->10.167.87.18:161: recvfrom: connection refused
	if strings.Contains(errmsg, " error establishing connection to host") && strings.Contains(errmsg, "i/o timeout") {
		errmsg = "i/o timeout"
	} else if strings.Contains(errmsg, "error reading from socket") && strings.Contains(errmsg, "recvfrom: connection refused") {
		errmsg = "connection refused"
	}
	value := PollStatusErr{
		Tstamp:   snmpResult.CollectTime,
		Ip:       snmpResult.Target.IP,
		PollType: polltype,
		Network:  snmpResult.Target.Network,
		Agent:    hostname,
		Errmsg:   errmsg,
	}
	return append(pollStatusErr, value)
}

func mergePollData(task *PollTrafficTask, target *SnmpTarget, ifTable *SnmpTable, zteIfTable *SnmpTable) map[string]*PollData {
	// ifInErrors for vendor = 'ZTE' and model = 'ZXCTN 6180H-A'
	// 	none:     use value from zteIfTable, if not found set to None
	// 	default:  use value from zteIfTable, if not found, use value from standard ifTable
	ret := make(map[string]*PollData)

	// create zteIfTable lookup
	zteIfTableLookup := make(map[string]*SnmpVar)
	if zteIfTable != nil {
		for _, row := range zteIfTable.Entries {
			zteIfTableLookup[row.Index] = row.Values["ifInErrors"]
		}
	}

	if ifTable != nil {
		for _, row := range ifTable.Entries {
			values := make(map[string]*SnmpVar)
			// values["ifIndex"] = row.Values["ifIndex"]
			// values["ifHighSpeed"] = row.Values["ifHighSpeed"]
			values["ifOperStatus"] = row.Values["ifOperStatus"]
			values["ifHCInOctets"] = row.Values["ifHCInOctets"]
			values["ifHCOutOctets"] = row.Values["ifHCOutOctets"]
			values["ifCounterDiscontinuityTime"] = row.Values["ifCounterDiscontinuityTime"]

			if task.ZteInErrors && target.IsZte_6180H() {
				if task.ZteInErrorsMode == "none" {
					// none: use value from zteIfTable, if not found set to None
					zteIfInErrors, ok := zteIfTableLookup[row.Index]
					if ok {
						values["ifInErrors"] = zteIfInErrors
					} else {
						log.Printf("Warn! %s, ifIndex=%s zteIfInErrors NotFound [none]", target.IP, row.Index)
					}
				} else if task.ZteInErrorsMode == "default" {
					// default: use value from zteIfTable, if not found, use value from standard ifTable
					zteIfInErrors, ok := zteIfTableLookup[row.Index]
					if ok {
						values["ifInErrors"] = zteIfInErrors
					} else {
						values["ifInErrors"] = row.Values["ifInErrors"]
						log.Printf("Warn! %s, ifIndex=%s zteIfInErrors NotFound [default]", target.IP, row.Index)
					}
				} else {
					log.Printf("Error! ZteInErrorsMode=%s is not supported", task.ZteInErrorsMode)
				}
			} else {
				values["ifInErrors"] = row.Values["ifInErrors"]
			}

			entry := PollData{
				Index:  row.Index,
				Values: values,
			}
			ret[row.Index] = &entry
		}
	}
	return ret
}

type PollData struct {
	Index  string
	Values map[string]*SnmpVar
}

func RoundDownTime(t time.Time, interval int) time.Time {
	if interval <= 0 {
		log.Fatalf("interval must be a positive number")
	}

	// Calculate the number of minutes since midnight
	minutesSinceMidnight := t.Hour()*60 + t.Minute()

	// Find the nearest interval
	roundedMinutes := (minutesSinceMidnight / interval) * interval

	// Get the new hour and minute
	newHour := roundedMinutes / 60
	newMinute := roundedMinutes % 60

	// Return the rounded time
	return time.Date(t.Year(), t.Month(), t.Day(), newHour, newMinute, 0, 0, t.Location())
}
