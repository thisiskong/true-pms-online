package snmplib

import (
	"encoding/hex"
	"fmt"
	"log"
	"math/big"
	"os"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	"github.com/gosnmp/gosnmp"
	"github.com/hako/durafmt"
	"go.uber.org/ratelimit"
)

var (
	logger gosnmp.Logger
	debug  = false
)

func SnmpDebugEnable() {
	logger = gosnmp.NewLogger(log.New(os.Stdout, "", 0))
}

func DebugEnable() {
	debug = true
}

func GetOid(setting *AppSetting, target SnmpTarget, oids []string, oidmap *map[string]SnmpOid) ([]SnmpVar, error) {
	var result *gosnmp.SnmpPacket = nil
	var err error = nil

	// build our own GoSNMP struct, rather than using g.Default
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(target.Timeout) * time.Second,
		ExponentialTimeout: target.ExpTime,
		Retries:            target.Retries,
		Logger:             logger,
	}

	err = params.Connect()
	if err != nil {
		log.Printf("GetOid(%s) Error: %v", target.IP, err)
		return nil, err
	}
	defer params.Conn.Close()

	result, err = params.Get(oids)
	if err != nil {
		// error
		return nil, err
	}

	// successful
	snmpVars := ParseSnmpOid(target, oidmap, result.Variables)
	log.Printf("GetOid(%s, %s) return %d entries", target.IP, target.Community, len(result.Variables))
	return snmpVars, nil
}

func GetNumEntries(tb *SnmpTableConfig, target *SnmpTarget) (int, error) {
	if tb.NumEntriesOid == "" {
		// NumEntries is disabled
		return -1, nil
	}
	params := &gosnmp.GoSNMP{
		Target:    target.IP,
		Port:      target.Port,
		Version:   target.Version,
		Community: target.Community,
		Timeout:   time.Duration(target.Timeout) * time.Second,
		Retries:   target.Retries,
	}
	err := params.Connect()
	if err != nil {
		log.Printf("getNumEntries: %s, %s, %s Error: %v", tb.Name, target.IP, target.Community, err)
		return 0, err
	}
	defer params.Conn.Close()

	// ifNumber.0
	result, err := params.Get([]string{tb.NumEntriesOid})
	if err != nil {
		log.Printf("getNumEntries: %s, %s, %s Error: %v", tb.Name, target.IP, target.Community, err)
		return 0, err
	} else {
		// log.Printf("getNumEntries: %s, %s, %s return %v", tb.Name, target.IP, target.Community, ToNumber(result.Variables[0]))
		val := ToNumber(result.Variables[0])
		switch val.(type) {
		case int64:
			ret := int(val.(int64))
			return ret, nil
		case uint64:
			return int(val.(uint64)), nil
		default:
			log.Printf("getNumEntries: %s, %s, %s Error: Not support type: %v", tb.Name, target.IP, target.Community, reflect.TypeOf(val))
			return 0, fmt.Errorf("not support type: %v", reflect.TypeOf(val))
		}
	}
}

func SnmpDiscovery(rl ratelimit.Limiter, topoRateLimit ratelimit.Limiter,
	mapper *Mapper, lookupService *LookupService, lldpMapper *LldpMapper,
	task *DiscoveryConfig, disc Discovery, target SnmpTarget, wg *sync.WaitGroup, tasksDone chan SnmpResult) {

	// acquire token, block if full
	rl.Take()
	topoRateLimit.Take()
	defer wg.Done()

	t := time.Now()

	// Icmp Ping
	var icmpResult IcmpPingResult
	if target.IcmpCount > 0 && target.IcmpTimeout > 0 {
		icmpResult = IcmpPing(&target, target.IcmpCount,
			time.Duration(target.IcmpInterval)*time.Millisecond,
			time.Duration(target.IcmpTimeout)*time.Millisecond)
		if !icmpResult.IsReachable() {
			tasksDone <- SnmpResult{Target: target, CollectTime: JsonTime(time.Now()), RespTime: time.Since(t).Milliseconds(), Error: icmpResult.ErrMsg(), IcmpPing: &icmpResult, Discovery: &disc}
			return
		}
	}

	var result *gosnmp.SnmpPacket = nil
	var err error = nil

	communityList := make([]string, 0, len(disc.Communities))
	// communityList = append(communityList, disc.Communities...)
	if target.Community != "" {
		// device already in inventory, try saved community first
		communityList = append(communityList, target.Community)
	}
	for _, community := range disc.Communities {
		if target.Community != community {
			communityList = append(communityList, community)
		}
	}

	// create list of request oid
	oids := task.Discovery.GetOidList(target)
	oidmap := task.Discovery.GetOidMap(target)

	for _, community := range communityList {
		result = nil
		err = nil

		// build our own GoSNMP struct, rather than using g.Default
		params := &gosnmp.GoSNMP{
			Target:             target.IP,
			Port:               target.Port,
			Version:            target.Version,
			Community:          community,
			Timeout:            time.Duration(target.Timeout) * time.Second,
			ExponentialTimeout: false,
			Retries:            1,
			// ExponentialTimeout: target.ExpTime,
			// Retries:            target.Retries,
			Logger: logger,
		}
		if disc.LocalAddr != nil {
			params.LocalAddr = *disc.LocalAddr
		}
		target.Community = community

		err = params.Connect()
		if err != nil {
			log.Printf("discovery: %s, %s Error: %v", target.IP, target.Community, err)
			// params.Conn.Close()
			break
		}
		// we must explicitly close connection, defer doesn't work here because it's in for loop
		// defer params.Conn.Close()

		// log.Printf("discovery: %s, %s, oids=%v", target.IP, target.Community, oids)
		result, err = params.Get(oids)
		if err == nil {
			// successful
			params.Conn.Close()
			break
		} else {
			// error, try next community string
			// log.Printf("discovery: %s, %s Error: %v", target.IP, target.Community, err)
			params.Conn.Close()
		}
	}

	if err != nil {
		// log.Printf("discovery: %s, %s Error: %v", target.IP, target.Community, err)
		tasksDone <- SnmpResult{Target: target, CollectTime: JsonTime(time.Now()), RespTime: time.Since(t).Milliseconds(), Error: err.Error(), IcmpPing: &icmpResult, Discovery: &disc}
		return
	}

	snmpVars := ParseSnmpOid(target, oidmap, result.Variables)
	log.Printf("discovery: %s, %s return %d entries", target.IP, target.Community, len(result.Variables))

	// Disable Discovery for some devices
	if isDisable_Discovery(snmpVars) {
		log.Printf("discovery: %s, %s NotProcess [NotDiscovery]", target.IP, target.Community)
		tasksDone <- SnmpResult{Target: target, CollectTime: JsonTime(time.Now()), RespTime: time.Since(t).Milliseconds(), SnmpVars: &snmpVars, IcmpPing: &icmpResult, Discovery: &disc, SaveDevice: false}
		return
	}

	// Get additional Oids
	oids2 := task.Discovery.GetExtOidList(target)
	snmpVars2, err := GetOid(task.Setting, target, oids2, oidmap)
	if err == nil {
		snmpVars = append(snmpVars, snmpVars2...)
	}

	// Some device having issue when handling concurrent snmp request
	useSequentialSnmpGet := isA10_TH14045(snmpVars)

	// ifTable
	snmpTables := make(map[string]*SnmpTable)
	ifTable, err := GetTable(task.Setting, &target, &task.Discovery.IfTable, useSequentialSnmpGet)
	if err != nil {
		ifTable = &SnmpTable{Name: task.Discovery.IfTable.Name, Error: err.Error()}
		snmpTables[task.Discovery.IfTable.Name] = ifTable
		log.Printf("discovery: %s, %s %s error: %v", target.IP, target.Community, task.Discovery.IfTable.Name, err)
	} else {
		snmpTables[task.Discovery.IfTable.Name] = ifTable
		log.Printf("discovery: %s, %s %s return %d entries", target.IP, target.Community, task.Discovery.IfTable.Name, len(ifTable.Entries))
	}

	// // ipAddrTable
	// ipAddrTable, err := GetTable(task.Setting, &target, &task.Discovery.IpAddrTable)
	// if err != nil {
	// 	ipAddrTable = &SnmpTable{Name: task.Discovery.IpAddrTable.Name, Error: err.Error()}
	// 	snmpTables[task.Discovery.IpAddrTable.Name] = ipAddrTable
	// 	log.Printf("discovery: %s, %s %s error: %v", target.IP, target.Community, task.Discovery.IpAddrTable.Name, err)
	// } else {
	// 	snmpTables[task.Discovery.IpAddrTable.Name] = ipAddrTable
	// 	log.Printf("discovery: %s, %s %s return %d entries", target.IP, target.Community, task.Discovery.IpAddrTable.Name, len(ipAddrTable.Entries))
	// }

	// lldpLocPortTable
	lldpLocPortTable, err := GetTable(task.Setting, &target, &task.Discovery.LldpLocPortTable, useSequentialSnmpGet)
	if err != nil {
		lldpLocPortTable = &SnmpTable{Name: task.Discovery.LldpLocPortTable.Name, Error: err.Error()}
		snmpTables[task.Discovery.LldpLocPortTable.Name] = lldpLocPortTable
		log.Printf("discovery: %s, %s %s error: %v", target.IP, target.Community, task.Discovery.LldpLocPortTable.Name, err)
	} else {
		snmpTables[task.Discovery.LldpLocPortTable.Name] = lldpLocPortTable
		log.Printf("discovery: %s, %s %s return %d entries", target.IP, target.Community, task.Discovery.LldpLocPortTable.Name, len(lldpLocPortTable.Entries))
	}

	// lldpRemTable
	lldpRemTable, err := GetTable(task.Setting, &target, &task.Discovery.LldpRemTable, useSequentialSnmpGet)
	if err != nil {
		lldpRemTable = &SnmpTable{Name: task.Discovery.LldpRemTable.Name, Error: err.Error()}
		snmpTables[task.Discovery.LldpRemTable.Name] = lldpRemTable
		log.Printf("discovery: %s, %s %s error: %v", target.IP, target.Community, task.Discovery.LldpRemTable.Name, err)
	} else {
		snmpTables[task.Discovery.LldpRemTable.Name] = lldpRemTable
		log.Printf("discovery: %s, %s %s return %d entries", target.IP, target.Community, task.Discovery.LldpRemTable.Name, len(lldpRemTable.Entries))
	}

	// vendor specific tables
	if target.Network == "FTTx" {
		for _, tb := range task.Discovery.ExtSnmpTables {
			if tb.Name == "lldpRemTable_FTTx_Dasan" ||
				tb.Name == "lldpRemTable_FTTx_Fiberhome" ||
				tb.Name == "lldpLocTable_FTTx_Raisecom" ||
				tb.Name == "lldpRemTable_FTTx_Raisecom" ||
				tb.Name == "lldpRemTable_FTTx_GCOM" {

				tbResult, err := WalkTable(task.Setting, &target, &tb)
				if err != nil {
					tbResult = &SnmpTable{Name: tb.Name, Error: err.Error()}
					snmpTables[tb.Name] = tbResult
					log.Printf("discovery: %s, %s %s error: %v", target.IP, target.Community, tb.Name, err)
				} else {
					snmpTables[tb.Name] = tbResult
					log.Printf("discovery: %s, %s %s return %d entries", target.IP, target.Community, tb.Name, len(tbResult.Entries))
				}
			}
		}
	}

	snmpResult := SnmpResult{
		Target:      target,
		CollectTime: JsonTime(time.Now()),
		RespTime:    time.Since(t).Milliseconds(),
		SnmpVars:    &snmpVars,
		IcmpPing:    &icmpResult,
		SnmpTables:  snmpTables, Discovery: &disc,
		SaveDevice: true}

	deviceInst, err := snmp2Device(&snmpResult, task, mapper, lldpMapper, lookupService)
	if err != nil {
		log.Printf("Error! %s: %v", snmpResult.Target.IP, err)
		tasksDone <- SnmpResult{Target: target, CollectTime: JsonTime(time.Now()), RespTime: time.Since(t).Milliseconds(), Error: err.Error(), SnmpVars: &snmpVars, IcmpPing: &icmpResult, Discovery: &disc, SaveDevice: false}
		return
	}
	if debug {
		logDevice(deviceInst)
	}
	snmpResult.Device = deviceInst

	tasksDone <- snmpResult
}

func GetTable(setting *AppSetting, target *SnmpTarget, tb *SnmpTableConfig, useSequentialSnmpGet bool) (*SnmpTable, error) {
	t := time.Now()
	numEntries, err := GetNumEntries(tb, target)
	if err != nil {
		log.Printf("getTable: %s, %s, %s Error: %v", tb.Name, target.IP, target.Community, err)
		return nil, err
	}

	oids := tb.GetColumnOids()
	oidmap := tb.GetColumnOidMap()

	variables, err := SnmpGetBulk(setting, target, oids, int(numEntries), useSequentialSnmpGet)
	respTime := time.Since(t).Milliseconds()

	if err != nil {
		// tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, Error: err.Error()}
		log.Printf("getTable: %s, %s, %s Error: %v", tb.Name, target.IP, target.Community, err)
		return nil, err

	} else {
		snmpTb := ParseSnmpTable(target, tb, oidmap, variables)
		// tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, SnmpTable: snmpTb}
		log.Printf("getTable: %s, %s, %s return %d entries, %d rows in %v ms.", tb.Name, target.IP, target.Community, len(variables), len(snmpTb.Entries), respTime)
		return snmpTb, nil
	}
}

func WalkTable(setting *AppSetting, target *SnmpTarget, tb *SnmpTableConfig) (*SnmpTable, error) {
	t := time.Now()
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(target.Timeout) * time.Second,
		ExponentialTimeout: target.ExpTime,
		Retries:            target.Retries,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("Error! %s|WalkTable: snmp_connect, Error: %v", target.IP, err)
		return nil, err
	}
	defer params.Conn.Close()

	oids := tb.GetColumnOids()
	oidmap := tb.GetColumnOidMap()

	var variables []gosnmp.SnmpPDU
	for _, oid := range oids {
		result, err := params.WalkAll(oid)
		if err != nil {
			log.Printf("walkTable: %s, %s, %s Error: %v", tb.Name, target.IP, target.Community, err)
			return nil, err
		}
		variables = append(variables, result...)
	}

	respTime := time.Since(t).Milliseconds()
	snmpTb := ParseSnmpTable(target, tb, oidmap, variables)
	// s, _ := json.MarshalIndent(resultTb, "", " ")
	// log.Printf("%s = %s", tb.Name, s)
	log.Printf("walkTable: %s, %s, %s return %d entries, %d rows in %v ms.", tb.Name, target.IP, target.Community, len(variables), len(snmpTb.Entries), respTime)
	return snmpTb, nil
}

func getMaxRepetition(setting *AppSetting, target SnmpTarget, maxRepetition uint32) error {
	// build our own GoSNMP struct, rather than using g.Default
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            5 * time.Second,
		ExponentialTimeout: false,
		Retries:            3,
		Logger:             logger,
	}
	err := params.Connect()
	if err != nil {
		log.Printf("getMaxRepetition: %s, %s, %d Error: %v", target.IP, target.Community, maxRepetition, err)
		return err
	}
	defer params.Conn.Close()

	_, err = params.GetBulk([]string{".1.3.6.1.2.1.2.2"}, 0, maxRepetition)
	if err != nil {
		log.Printf("getMaxRepetition: %s, %s, %d Error: %v", target.IP, target.Community, maxRepetition, err)
		return err
	}
	log.Printf("getMaxRepetition: %s, %s, %d Success", target.IP, target.Community, maxRepetition)
	return nil
}

func SnmpGetBulk(setting *AppSetting, target *SnmpTarget, oids []string, nrow int, useSequentialSnmpGet bool) ([]gosnmp.SnmpPDU, error) {
	if useSequentialSnmpGet {
		var variables []gosnmp.SnmpPDU
		for i := 0; i < len(oids); i++ {
			result := SnmpGetBulkSequential(setting, *target, oids[i], nrow)
			if result.Error == nil {
				variables = append(variables, result.Variables...)
			} else {
				// some of worker return error
				return variables, result.Error
			}
			time.Sleep(5 * time.Second)
		}
		return variables, nil

	} else {
		var wg sync.WaitGroup
		var variables []gosnmp.SnmpPDU

		rl := getHostRateLimit(setting, target)
		ch := make(chan SnmpPartialResult)
		wg.Add(len(oids))
		for i := 0; i < len(oids); i++ {
			go SnmpGetBulkWorker(setting, *target, &wg, rl, oids[i], nrow, ch)
		}
		for i := 0; i < len(oids); i++ {
			result := <-ch
			if result.Error == nil {
				variables = append(variables, result.Variables...)
			} else {
				// some of worker return error
				return variables, result.Error
			}
		}
		wg.Wait()
		return variables, nil
	}
}

func SnmpGetBulkWorker(setting *AppSetting, target SnmpTarget, wg *sync.WaitGroup, rl ratelimit.Limiter, oid string, nrow int, ch chan SnmpPartialResult) {
	// acquire token, block if full
	rl.Take()
	defer wg.Done()

	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(target.Timeout) * time.Second,
		ExponentialTimeout: target.ExpTime,
		Retries:            target.Retries,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("Error! %s|SnmpGetBulkWorker: snmp_connect, Error: %v", target.IP, err)
		ch <- SnmpPartialResult{Error: err}
		return
	}
	defer params.Conn.Close()

	req_oid := oid
	cnt := 0
	ret := SnmpPartialResult{}
	for {
		cnt += 1
		// log.Printf("SnmpGetBulkWorker(%s, %s) {%s} {%d}", target.IP, target.Community, req_oid, cnt)
		maxRepetition := maxRepetition(&target, nrow, len(ret.Variables))
		// log.Printf("SnmpGetBulkWorker {%s}, nrows=%d, prows=%d, maxRepetition=%d", req_oid, nrow, len(ret.Variables), maxRepetition)
		result, err := params.GetBulk([]string{req_oid}, 0, uint32(maxRepetition))
		if err != nil {
			log.Printf("Error! %s|SnmpGetBulkWorker: oid={%s}, cnt={%d}, Error: %v", target.IP, req_oid, cnt, err)
			ret.Error = err
			break

		} else {
			ret.Variables = append(ret.Variables, result.Variables...)
			// first := result.Variables[0].Name
			// last := result.Variables[len(result.Variables)-1].Name
			// log.Printf("SnmpGetBulkWorker(%s, %s) {%s} {%d} {%s} {%s}", target.IP, target.Community, req_oid, cnt, first, last)
		}
		if isEndOfOid(&result.Variables, oid) || nrow == len(ret.Variables) {
			break
		}
		req_oid = result.Variables[len(result.Variables)-1].Name
	}
	// log.Printf("SnmpGetBulkWorker(%s, %s) {%s} Done", target.IP, target.Community, oid)
	ch <- ret
}

func SnmpGetBulkSequential(setting *AppSetting, target SnmpTarget, oid string, nrow int) SnmpPartialResult {
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(target.Timeout) * time.Second,
		ExponentialTimeout: target.ExpTime,
		Retries:            target.Retries,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("Error! %s|SnmpGetBulkSequential: snmp_connect, Error: %v", target.IP, err)
		return SnmpPartialResult{Error: err}
	}
	defer params.Conn.Close()

	req_oid := oid
	cnt := 0
	ret := SnmpPartialResult{}
	for {
		cnt += 1
		// log.Printf("SnmpGetBulkSequential(%s, %s) {%s} {%d}", target.IP, target.Community, req_oid, cnt)
		maxRepetition := maxRepetition(&target, nrow, len(ret.Variables))
		// log.Printf("SnmpGetBulkSequential {%s}, nrows=%d, prows=%d, maxRepetition=%d", req_oid, nrow, len(ret.Variables), maxRepetition)
		result, err := params.GetBulk([]string{req_oid}, 0, uint32(maxRepetition))
		if err != nil {
			log.Printf("Error! %s|SnmpGetBulkSequential: oid={%s}, cnt={%d}, Error: %v", target.IP, req_oid, cnt, err)
			ret.Error = err
			break

		} else {
			ret.Variables = append(ret.Variables, result.Variables...)
			// first := result.Variables[0].Name
			// last := result.Variables[len(result.Variables)-1].Name
			// log.Printf("SnmpGetBulkSequential(%s, %s) {%s} {%d} {%s} {%s}", target.IP, target.Community, req_oid, cnt, first, last)
		}
		if isEndOfOid(&result.Variables, oid) || nrow == len(ret.Variables) {
			break
		}
		req_oid = result.Variables[len(result.Variables)-1].Name
	}
	// log.Printf("SnmpGetBulkSequential(%s, %s) {%s} Done", target.IP, target.Community, oid)
	return ret
}

func SnmpPollTraffic(globalRateLimit ratelimit.Limiter, topoRateLimit ratelimit.Limiter,
	setting *AppSetting, task *PollTrafficConfig, target SnmpTarget, wg *sync.WaitGroup, tasksDone chan SnmpResult) {

	// acquire token, block if full
	globalRateLimit.Take()
	topoRateLimit.Take()
	defer wg.Done()
	t := time.Now()

	// IcmpPing
	var icmpResult IcmpPingResult
	if target.IcmpCount > 0 && target.IcmpTimeout > 0 {
		icmpResult = IcmpPing(&target, target.IcmpCount,
			time.Duration(target.IcmpInterval)*time.Millisecond,
			time.Duration(target.IcmpTimeout)*time.Millisecond)
		if !icmpResult.IsReachable() {
			log.Printf("IcmpPing: %s, %s", target.IP, icmpResult.ErrMsg())
			tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: time.Since(t).Milliseconds(), Error: icmpResult.ErrMsg(), IcmpPing: &icmpResult}
			return
		}
	}

	if task.PollTraffic.GetSelectedIntf {
		// get selected interfaces
		snmpTables, err := getTraffic(setting, task, &target)
		if err != nil {
			tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: time.Since(t).Milliseconds(), Error: err.Error()}
			return
		} else {
			tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: time.Since(t).Milliseconds(), SnmpTables: snmpTables}
			return
		}

	} else {
		// ifXTable Num Entries
		var numEntries = -1
		if task.PollTraffic.IfTable.NumEntriesOid != "" {
			var err error
			numEntries, err = GetNumEntries(&task.PollTraffic.IfTable, &target)
			if err != nil {
				snmpTable := SnmpTable{Name: task.PollTraffic.IfTable.Name, Error: err.Error()}
				snmpTables := map[string]*SnmpTable{task.PollTraffic.IfTable.Name: &snmpTable}
				tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: time.Since(t).Milliseconds(), Error: err.Error(), SnmpTables: snmpTables}
				return
			}
		}

		// ifXTable, zteCrcTable
		snmpTables := make(map[string]*SnmpTable)

		ifTable := GetSnmpTable(setting, &task.PollTraffic.IfTable, target, numEntries, false)
		snmpTables["ifTable"] = ifTable

		if task.PollTraffic.ZteInErrors && target.IsZte_6180H() {
			zteIfTable := GetSnmpTable(setting, &task.PollTraffic.ZteIfTable, target, numEntries, false)
			snmpTables["zteIfTable"] = zteIfTable
		}

		respTime := time.Since(t).Milliseconds()
		tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, SnmpTables: snmpTables}
	}

	// ifXTable
	// oids := task.PollTraffic.IfTable.GetColumnOids()
	// oidmap := task.PollTraffic.IfTable.GetColumnOidMap()

	// variables, err := SnmpGetBulk(setting, &target, oids, int(numEntries))
	// respTime := time.Since(t).Milliseconds()

	// if err != nil {
	// 	snmpTable := SnmpTable{Name: task.PollTraffic.IfTable.Name, Error: err.Error()}
	// 	snmpTables := map[string]*SnmpTable{task.PollTraffic.IfTable.Name: &snmpTable}
	// 	tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, Error: err.Error(), SnmpTables: snmpTables}
	// 	log.Printf("getSnmpTable: %s, %s, %s Error: %v", target.IP, target.Community, task.PollTraffic.IfTable.Name, err)

	// } else {
	// 	snmpTable := ParseSnmpTable(&task.PollTraffic.IfTable, oidmap, variables)
	// 	snmpTables := map[string]*SnmpTable{task.PollTraffic.IfTable.Name: snmpTable}
	// 	tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, SnmpTables: snmpTables}
	// 	// log.Printf("getSnmpTable: %s, %s, %s return %d entries, %d rows in %v ms.", target.IP, target.Community, task.Name, len(variables), len(snmpTable.Entries), respTime)
	// }

	// // zteCrcTable
	// if target.Vendor != nil && *target.IsZte6180H() {
	// 	oids := task.PollTraffic.ZteCrcTable.GetColumnOids()
	// 	oidmap := task.PollTraffic.ZteCrcTable.GetColumnOidMap()

	// 	variables, err := SnmpGetBulk(setting, &target, oids, int(numEntries))
	// 	respTime := time.Since(t).Milliseconds()

	// 	if err != nil {

	// 	} else {
	// 		zteCrcTable := ParseSnmpTable(&task.PollTraffic.ZteCrcTable, oidmap, variables)
	// 		snmpTables := map[string]*SnmpTable{task.PollTraffic.ZteCrcTable.Name: zteCrcTable}
	// 		tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, SnmpTables: snmpTables}
	// 	}
	// }
}

func GetSnmpTable(setting *AppSetting, tb *SnmpTableConfig, target SnmpTarget, numEntries int, useSequentialalGetTable bool) *SnmpTable {
	t := time.Now()
	oids := tb.GetColumnOids()
	oidmap := tb.GetColumnOidMap()

	variables, err := SnmpGetBulk(setting, &target, oids, int(numEntries), useSequentialalGetTable)
	if err != nil {
		snmpTable := SnmpTable{Name: tb.Name, Error: err.Error()}
		// snmpTables := map[string]*SnmpTable{tb.Name: &snmpTable}
		// tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, Error: err.Error(), SnmpTables: snmpTables}
		respTime := time.Since(t).Milliseconds()
		log.Printf("Error! %s|getSnmpTable: %s, Error: %v in %v ms.", target.IP, tb.Name, err, respTime)
		return &snmpTable

	} else {
		snmpTable := ParseSnmpTable(&target, tb, oidmap, variables)
		// snmpTables := map[string]*SnmpTable{task.PollTraffic.IfTable.Name: snmpTable}
		// tasksDone <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, RespTime: respTime, SnmpTables: snmpTables}
		respTime := time.Since(t).Milliseconds()
		log.Printf("getSnmpTable: %s, %s, %s return %d rows in %v ms.", target.IP, target.Community, tb.Name, len(snmpTable.Entries), respTime)
		return snmpTable
	}
}

func ParseSnmpOid(target SnmpTarget, oidmap *map[string]SnmpOid, variables []gosnmp.SnmpPDU) []SnmpVar {
	snmpVars := make([]SnmpVar, 0, len(variables))
	for _, variable := range variables {
		snmpOid, ok := (*oidmap)[variable.Name]
		if ok {
			value, err := ToValue(&snmpOid, variable)
			if err != nil {
				log.Printf("Error! %v|%v", target.IP, err)
			} else {
				snmpVars = append(snmpVars, SnmpVar{Oid: variable.Name, Type: variable.Type.String(), Name: snmpOid.Name, Value: value})
				// log.Printf("%-40s %-20s %-20s %s %s %s\n", variable.Name, variable.Type, prefix, oid_idx, oid.Field, ToString(variable))
			}
		}
	}
	return snmpVars
}

func ParseSnmpTable(target *SnmpTarget, snmptb *SnmpTableConfig, oidmap *map[string]SnmpOid, variables []gosnmp.SnmpPDU) *SnmpTable {
	rows := make(map[string]*SnmpTableEntry)

	for _, variable := range variables {
		// --- Do Not Check TableOid Prefix ---
		// --- Otherwise, get ifDescr on table ifXTable won't work ---
		// if !strings.HasPrefix(variable.Name, task.TableOid) {
		// 	// end-of-table
		// 	continue
		// }

		// --- Following code won't works when polling mix column from 2 tables such as ifDescr + ifXTable
		// log.Println(variable)
		// tokens := strings.Split(variable.Name, ".")
		// m := len(strings.Split(task.TableOid, ".")) + 2
		// col_oid := strings.Join(tokens[:m], ".")
		// row_id := strings.Join(tokens[m:], ".")
		// log.Printf("oid = %-40s col_oid = %-30s row_id = %s", variable.Name, col_oid, row_id)
		// snmpOid, ok := (*oidmap)[col_oid]
		// if !ok {
		// 	// column oid not in mib file
		// 	continue
		// }

		var snmpOid *SnmpOid
		var row_id string = ""
		// var col_oid string = ""
		for _, oid := range *oidmap {
			if strings.HasPrefix(variable.Name, oid.Oid+".") {
				snmpOid = &oid
				// col_oid = oid.Oid
				row_id = strings.Replace(variable.Name, oid.Oid+".", "", 1)
				break
			}
		}
		if snmpOid == nil {
			// column oid not in mib file
			continue
		}
		// val := ToValue(snmpOid, variable)
		// log.Printf("oid = %-40s col_oid = %-30s row_id = %-5s val = %v", variable.Name, col_oid, row_id, val)
		// log.Printf("%-40s %-20s %-20s %s\n", variable.Name, variable.Type, snmpOid.Name, ToString(variable))
		value, err := ToValue(snmpOid, variable)
		if err != nil {
			log.Printf("Error! %s|%v", target.IP, err)

		} else {
			// log.Printf("Debug: %-40s %-20s %-20s %-20s %s\n", variable.Name, variable.Type, snmpOid.Name, row_id, ToString(variable))
			// FTTx: There's a case where ifIndex return invalid value (negative value) due to overflow (such as FTTx Huawei, model: MA5600V8)
			// Therefore, for ifIndex, we use row_id as value
			if snmpOid.Name == "ifIndex" {
				val, err := strconv.ParseInt(row_id, 10, 64)
				if err != nil {
					log.Printf("Error! %s|%v", target.IP, err)
				} else {
					value = val
				}
			}
			snmpVar := SnmpVar{Oid: variable.Name, Type: variable.Type.String(), Name: snmpOid.Name, Value: value}
			entry, ok := rows[row_id]
			if !ok {
				entry = &SnmpTableEntry{Index: row_id, Values: make(map[string]*SnmpVar)}
				entry.Values[snmpVar.Name] = &snmpVar
				rows[row_id] = entry
			} else {
				entry.Values[snmpVar.Name] = &snmpVar
			}
		}
	}

	entries := make([]SnmpTableEntry, 0, len(rows))
	for _, value := range rows {
		entries = append(entries, *value)
	}

	// j, _ := json.MarshalIndent(entries, "", " ")
	// log.Printf("%v", string(j))

	return &SnmpTable{Name: snmptb.Name, Entries: entries}
}

func ToString(pdu gosnmp.SnmpPDU) string {
	switch pdu.Type {
	case gosnmp.OctetString:
		byteArray := pdu.Value.([]byte)
		if isASCII(string(byteArray)) {
			return string(byteArray)
		} else {
			encodedString := hex.EncodeToString(byteArray)
			return encodedString
		}
	case gosnmp.TimeTicks:
		timetick := gosnmp.ToBigInt(pdu.Value)
		duration := time.Duration(timetick.Uint64()/100) * time.Second
		text := durafmt.Parse(duration).LimitToUnit("days").String()
		return fmt.Sprintf("%s [%s]", timetick.String(), text)
	default:
		return gosnmp.ToBigInt(pdu.Value).String()
	}
}

func ToNumber(pdu gosnmp.SnmpPDU) interface{} {
	// log.Printf("ToNumber %v = %v {%v} {%v}", pdu.Name, pdu.Value, pdu.Type, reflect.TypeOf(pdu.Value))
	switch pdu.Type {
	case gosnmp.TimeTicks, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Uinteger32:
		// 0..4294967295
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64()
	case gosnmp.Integer:
		// -2147483648..2147483647
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Int64()
	case gosnmp.Counter64:
		// 0..18446744073709551615
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64()
	default:
		str := ToString(pdu)
		ival, err := strconv.ParseUint(str, 10, 64)
		if err != nil {
			log.Printf("Error! ToNumber: %v {%v} {%v} err={%v}", pdu.Name, pdu.Type, pdu.Value, err)
			return 0
		}
		return ival
	}
}

func ToValue(snmpOid *SnmpOid, pdu gosnmp.SnmpPDU) (interface{}, error) {
	// log.Printf("ToValue %v = %v {%v} {%v} {%v}", pdu.Name, pdu.Value, pdu.Type, reflect.TypeOf(pdu.Value), snmpOid.Name)
	switch pdu.Type {
	case gosnmp.TimeTicks, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Uinteger32:
		// 0..4294967295
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64(), nil
	case gosnmp.Counter64:
		// 0..18446744073709551615
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64(), nil
	case gosnmp.Integer:
		// -2147483648..2147483647
		val := gosnmp.ToBigInt(pdu.Value)
		if snmpOid.Enum != nil {
			// log.Printf("enum: %v, %v", bigInt.Int64(), snmpOid.Enum)
			enum, ok := snmpOid.Enum[int(val.Int64())]
			if ok {
				return enum, nil
			} else {
				return fmt.Sprintf("%d", val.Int64()), nil
			}
		} else {
			return val.Int64(), nil
		}
	case gosnmp.OctetString, gosnmp.IPAddress:
		if byteArray, ok := pdu.Value.([]byte); ok {
			// There's a case for Nokia OLT that ifHCInOctets & ifHCOutOctets for Uplink port use String type instead of Counter64
			// We check if incoming type is String and SnmpOid.Name either ifHCInOctets or ifHCOutOCtets
			// then convert HexString to Uint64
			if snmpOid.Name == "ifHCInOctets" || snmpOid.Name == "ifHCOutOctets" {
				hexStr := hex.EncodeToString(byteArray)
				val := new(big.Int)
				_, ok := val.SetString(hexStr, 16)
				if ok {
					// log.Printf("hexString={0x%v} = %v", hexStr, val)
					return val.Uint64(), nil
				}
				return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)

			} else if snmpOid.Syntax == "PhysAddress" {
				addr := []string{}
				for i := 0; i < len(byteArray); i++ {
					addr = append(addr, hex.EncodeToString([]byte{byteArray[i]}))
				}
				return strings.Join(addr, ":"), nil
			} else {
				if isASCII(string(byteArray)) {
					return string(byteArray), nil
				} else {
					return hex.EncodeToString(byteArray), nil
				}
			}
		}
		if strValue, ok := pdu.Value.(string); ok {
			return strValue, nil
		}
		return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)
	case gosnmp.ObjectIdentifier:
		return pdu.Value, nil
	case gosnmp.EndOfContents:
		return nil, nil
	case gosnmp.EndOfMibView:
		return nil, nil
	case gosnmp.NoSuchInstance:
		return nil, fmt.Errorf("NoSuchInstance: name=%v, type=%v", pdu.Name, pdu.Type)
	case gosnmp.NoSuchObject:
		return nil, fmt.Errorf("NoSuchObject: name=%v, type=%v", pdu.Name, pdu.Type)
	default:
		return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)
	}
}

func PrintValue(pdu gosnmp.SnmpPDU) error {
	log.Printf("%-30s = ", pdu.Name)
	switch pdu.Type {
	case gosnmp.OctetString:
		byteArray := pdu.Value.([]byte)
		if isASCII(string(byteArray)) {
			log.Printf("{string} %s\n", string(byteArray))
		} else {
			encodedString := hex.EncodeToString(byteArray)
			log.Printf("{ipaddr} %s\n", encodedString)
		}
	default:
		log.Printf("{number} %d\n", gosnmp.ToBigInt(pdu.Value))
	}
	return nil
}

func isASCII(value string) bool {
	for _, c := range value {
		if c > unicode.MaxASCII {
			return false
		}
	}
	return true
}

func isEndOfOid(variables *[]gosnmp.SnmpPDU, oid string) bool {
	if len(*variables) == 0 {
		return true
	}
	for _, variable := range *variables {
		if !strings.HasPrefix(variable.Name, oid) {
			return true
		}
	}
	return false
}

func maxRepetition(target *SnmpTarget, total_row int, processed_row int) int {
	if total_row == -1 {
		return int(target.MaxRepetition)
	} else {
		remain_row := total_row - processed_row
		if remain_row <= int(target.MaxRepetition) {
			return remain_row
		} else {
			return int(target.MaxRepetition)
		}
	}
}

func getHostRateLimit(setting *AppSetting, target *SnmpTarget) ratelimit.Limiter {
	// some small device having problem with frequent query so we decrease rate limit
	if target.IsA10_TH14045() {
		return ratelimit.New(1, ratelimit.Per(5*time.Second))
	} else {
		return ratelimit.New(setting.HostRateLimit)
	}
}

func getTraffic(setting *AppSetting, task *PollTrafficConfig, target *SnmpTarget) (map[string]*SnmpTable, error) {
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(target.Timeout) * time.Second,
		ExponentialTimeout: target.ExpTime,
		Retries:            target.Retries,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("Error! %s|getTraffic: snmp_connect, Error: %v", target.IP, err)
		return nil, err
	}
	defer params.Conn.Close()

	t := time.Now()
	snmpTables := make(map[string]*SnmpTable)
	ifTable, err := getTableByOid(params, target, task.PollTraffic.IfTable)
	if err != nil {
		return nil, err
	}
	log.Printf("getTraffic: %s [ifTable] return %d entries in %v", target.IP, len(ifTable.Entries), time.Since(t).Milliseconds())
	snmpTables[ifTable.Name] = ifTable

	if task.PollTraffic.ZteInErrors && target.IsZte_6180H() {
		t := time.Now()
		zteIfTable, err := getTableByOid(params, target, task.PollTraffic.ZteIfTable)
		if err != nil {
			return nil, err
		}
		log.Printf("getTraffic: %s [zteIfTable] return %d entries in %v", target.IP, len(zteIfTable.Entries), time.Since(t).Milliseconds())
		snmpTables[zteIfTable.Name] = zteIfTable
	}
	return snmpTables, nil
}

func mapSnmpOid(oidmap *map[string]SnmpOid, variable gosnmp.SnmpPDU) (*SnmpOid, string) {
	var snmpOid *SnmpOid
	var row_id string
	for _, oid := range *oidmap {
		if strings.HasPrefix(variable.Name, oid.Oid+".") {
			snmpOid = &oid
			// col_oid = oid.Oid
			row_id = strings.Replace(variable.Name, oid.Oid+".", "", 1)
			return snmpOid, row_id
		}
	}
	return nil, ""
}

func createOidList(target *SnmpTarget, oidmap *map[string]SnmpOid) [][]string {
	// log.Printf("createOidList: %s, intf.length = %d, target.IP, len(target.Interfaces))
	oidList := make([][]string, 0)
	oids := make([]string, 0)
	for ifindex := range target.Interfaces {
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.2.2.1.1.%s", ifindex))     // ifIndex
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.31.1.1.1.6.%s", ifindex))  // ifHCInOctets
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.31.1.1.1.10.%s", ifindex)) // ifHCOutOctets
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.31.1.1.1.19.%s", ifindex)) // ifCounterDiscontinuityTime
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.2.2.1.8.%s", ifindex))     // ifOperStatus
		// oids = append(oids, fmt.Sprintf(".1.3.6.1.2.1.2.2.1.14.%s", ifindex))    // ifInErrors
		for _, snmpOid := range *oidmap {
			oids = append(oids, fmt.Sprintf("%s.%s", snmpOid.Oid, ifindex))
			oids_len := len(oids)
			if oids_len%target.MaxReqOid == 0 {
				oidList = append(oidList, oids)
				oids = make([]string, 0)
			}
		}
	}
	if len(oids) > 0 {
		oidList = append(oidList, oids)
	}
	// log.Printf("createOidList: %s, intf.length = %d, return %d", target.IP, len(target.Interfaces), len(oidList))
	return oidList
}

func getTableByOid(params *gosnmp.GoSNMP, target *SnmpTarget, tbconfig SnmpTableConfig) (*SnmpTable, error) {
	start := time.Now()
	timeout := time.Duration(180) * time.Second
	oidmap := tbconfig.GetColumnOidMap()
	tableEntries := make(map[string]SnmpTableEntry)
	ifTableOidList := createOidList(target, oidmap)
	for _, oids := range ifTableOidList {
		if time.Since(start) > timeout {
			log.Printf("Error! %s|TimeoutExceed", target.IP)
			break
		}

		result, err := params.Get(oids)
		if err != nil {
			return nil, err
		}

		if target.HasFlag_RetryOnNoInstance() {
			if isNoSuchInstanceOrNoSuchObject(target, result) {
				for i := 1; i <= 3; i++ {
					time.Sleep(10 * time.Second)
					result, err = params.Get(oids)
					if err != nil {
						return nil, err
					}
					if !isNoSuchInstanceOrNoSuchObject(target, result) {
						break
					}
				}
			}
		}

		for _, variable := range result.Variables {
			snmpOid, row_id := mapSnmpOid(oidmap, variable)
			if row_id == "" {
				log.Printf("Error! %s|RowIdIsNull|%v", target.IP, variable)
				continue
			}
			value, err := ToValue(snmpOid, variable)
			if err != nil {
				log.Printf("Error! %s|%v", target.IP, err)
				continue
			}

			snmpVar := SnmpVar{Oid: variable.Name, Type: variable.Type.String(), Name: snmpOid.Name, Value: value}
			entry, ok := tableEntries[row_id]
			if !ok {
				entry = SnmpTableEntry{Index: row_id, Values: make(map[string]*SnmpVar)}
				entry.Values[snmpVar.Name] = &snmpVar
				tableEntries[row_id] = entry
			} else {
				entry.Values[snmpVar.Name] = &snmpVar
			}
		}
	}

	tb := SnmpTable{Name: tbconfig.Name, Entries: make([]SnmpTableEntry, 0)}

	// convert from map to list
	for _, row := range tableEntries {
		tb.Entries = append(tb.Entries, row)
	}
	return &tb, nil
}

func isNoSuchInstanceOrNoSuchObject(target *SnmpTarget, result *gosnmp.SnmpPacket) bool {
	for _, pdu := range result.Variables {
		switch pdu.Type {
		case gosnmp.NoSuchInstance, gosnmp.NoSuchObject:
			return true
		}
	}
	return false
}

func isA10_TH14045(snmpVars []SnmpVar) bool {
	for _, snmpvar := range snmpVars {
		if snmpvar.Name == "sysDescr" {
			switch snmpvar.Value.(type) {
			case string:
				if strings.Contains(snmpvar.Value.(string), "Thunder Series Unified Application Service Gateway TH14045") {
					return true
				}
			}
		}
	}
	return false
}

func isDisable_Discovery(snmpVars []SnmpVar) bool {
	// Disable discovery
	// ZTE: 			sysDescr = "ZTE ACCESS NODE AGENT" or sysDescr = "ACCESS NODE AGENT"
	// Huawei MA5600V3	sysDescr = "Huawei Integrated Access Software" and hwSysVersion contains "MA5600V3"
	// Huawei MA5616	sysDescr = "Huawei Integrated Access Software" and hwSysVersion contains "MA5616"
	sysDescr := ""
	hwSysVersion := ""
	for _, snmpvar := range snmpVars {
		if snmpvar.Name == "sysDescr" {
			switch snmpvar.Value.(type) {
			case string:
				sysDescr = snmpvar.Value.(string)
			}
		} else if snmpvar.Name == "hwSysVersion" {
			switch snmpvar.Value.(type) {
			case string:
				hwSysVersion = snmpvar.Value.(string)
			}
		}
	}
	if sysDescr == "ZTE ACCESS NODE AGENT" || sysDescr == "ACCESS NODE AGENT" {
		return true
	}
	if sysDescr == "Huawei Integrated Access Software" && (strings.Contains(hwSysVersion, "MA5600V3") || strings.Contains(hwSysVersion, "MA5616")) {
		return true
	}
	return false
}
