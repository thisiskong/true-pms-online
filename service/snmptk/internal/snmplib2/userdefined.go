package snmplib2

import (
	"fmt"
	"log"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gosnmp/gosnmp"
)

func (job *SnmpBulkGetJob) CreateOidList(target *SnmpTarget) [][]string {

	if job.RequestStrategy == "get" {
		// snmpget for single oid
		return createOidList_Dot0(target, job)
	} else {
		// row for table
		return createOidList_PonPort(target, job)
	}
}

func (job *SnmpBulkGetJob) MapSnmpVar(target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {

	if job.RequestStrategy == "get" {
		// snmpget for single oid
		return mapSnmpVar_Standard(job, target, snmpOid, collectTime, variable)

	} else {
		// row or column for table
		if job.MapToObjType == "olt-pon" {
			// oltpon60m.yml
			return mapSnmpVar_OltPon(job, target, snmpOid, collectTime, variable)

		} else if job.MapToObjType == "olt-pon-traffic" {
			// pontraffic60m.yml
			return mapSnmpVar_OltPonTraffic(job, target, snmpOid, collectTime, variable)

		} else if job.MapToObjType == "olt-uplink" {
			// oltuplink60m.yml
			return mapSnmpVar_OltUplink(job, target, snmpOid, collectTime, variable)

		} else if job.MapToObjType == "onu-pon" {
			// onupon60m.yml
			return mapSnmpVar_OnuPon(job, target, snmpOid, collectTime, variable)
		}

		log.Printf("Error! mapToObjType: %s not supported", job.MapToObjType)
		return nil
	}
}

func createOidList_Dot0(target *SnmpTarget, job *SnmpBulkGetJob) [][]string {
	maxReqOid := target.MaxReqOid
	if job.MaxReqOid > 0 {
		maxReqOid = job.MaxReqOid
	}
	oidList := make([][]string, 0)
	oids := make([]string, 0)
	for _, snmpOid := range job.Oids {
		oids = append(oids, fmt.Sprintf("%s.0", snmpOid.Oid))
		oids_len := len(oids)
		if oids_len%maxReqOid == 0 {
			oidList = append(oidList, oids)
			oids = make([]string, 0)
		}
	}
	if len(oids) > 0 {
		oidList = append(oidList, oids)
	}
	return oidList
}

func createOidList_PonPort(target *SnmpTarget, job *SnmpBulkGetJob) [][]string {
	maxReqOid := target.MaxReqOid
	if job.MaxReqOid > 0 {
		maxReqOid = job.MaxReqOid
	}
	oidList := make([][]string, 0)
	oids := make([]string, 0)
	for ifIndex := range target.PonPortsIfIndex {
		for _, snmpOid := range job.Oids {
			oids = append(oids, fmt.Sprintf("%s.%s", snmpOid.Oid, ifIndex))
			oids_len := len(oids)
			if oids_len%maxReqOid == 0 {
				oidList = append(oidList, oids)
				oids = make([]string, 0)
			}
		}
	}
	if len(oids) > 0 {
		oidList = append(oidList, oids)
	}
	return oidList
}

func mapSnmpVar_Standard(job *SnmpBulkGetJob, target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {
	val, err := ToValue(snmpOid, variable)
	if err != nil {
		log.Printf("Error! %s invalid value: %v", target.IP, variable)
		return nil
	}
	snmpVar := SnmpVar{
		CollectTime: JsonTime(collectTime),
		ObjType:     job.ObjType,
		RowId:       fmt.Sprintf("%v", val),
		SnmpName:    snmpOid.Name,
		SnmpValue:   val,
	}
	return &snmpVar
}

func mapSnmpVar_OltPonTraffic(job *SnmpBulkGetJob, target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {
	// return: rowIndex, ifIndex, ontId, ponPort, l1sp, ifoper, ifspeed
	ifIndex := ""
	ifName := ""
	ontId := ""
	ponPort := ""
	l1sp := ""
	ifSpeed := int64(0)
	rowId := ""
	name := snmpOid.Name
	rowIndex := strings.Replace(variable.Name, snmpOid.Oid+".", "", 1)
	tokens := strings.Split(rowIndex, ".")
	len := len(tokens)
	if len == 1 {
		ifIndex = tokens[0]
		rowId = ifIndex
	} else if len == 2 || len == 3 {
		ifIndex = tokens[0]
		ontId = tokens[1]
		rowId = fmt.Sprintf("%s.%s", ifIndex, ontId)
	}

	val, err := ToValue(snmpOid, variable)
	if err != nil {
		log.Printf("Error! %s invalid value: %v", target.IP, variable)
		return nil
	}

	// ZTE C6XX model with dual channel
	if target.Vendor == "ZTE" && job.Name == "pon-traffic3" {
		ifIndex, ponpontStr, wavelength, retcode := zte_olt_pon_rowId_to_PonPort(rowIndex)
		// log.Printf("zte: %s|%v|%v|%v", rowIndex, ponpontStr, wavelength, retcode)
		if retcode == -1 {
			return nil
		}

		if ifIndex != "" {
			// zte_in_octets, zte_out_octets
			ponport, ok := target.PonPortsIfIndex[ifIndex]
			if ok {
				ifIndex = ponport.Ifindex
				rowId = ponport.Ifindex
				ifSpeed = ponport.Ifspeed
				ponPort = ponport.PonPort
				l1sp = ponport.L1sp
			}
			// do not rename variable: zte_in_octets, zte_out_octets
		} else {
			// zte_in_octets1490, zte_out_octets1490
			// zte_in_octets1577, zte_out_octets1577
			// -------------------------------------
			// wavelength
			// 	- GPON: "" (blank)
			//	- XGPON: "1490" or "1577"
			// rename variable:
			// zte_in_octets   --> zte_in_octets{wavelength}
			// zte_out_octets	 --> zte_out_octets{wavelength}
			name = fmt.Sprintf("%s%s", name, wavelength)
			ponport, ok := target.PonPortsName[ponpontStr]
			if ok {
				ifIndex = ponport.Ifindex
				rowId = ponport.Ifindex
				ifSpeed = ponport.Ifspeed
				ponPort = ponport.PonPort
				l1sp = ponport.L1sp
			}
		}
		// log.Printf("zte-pon-traffic3: %s|%s|%s|%s|%s|%d|%s|%v", variable.Name, rowId, ifIndex, ponpontStr, wavelength, retcode, name, val)

	} else {

		if ifIndex != "" {
			rec, ok := target.PonPortsIfIndex[ifIndex]
			if !ok {
				// Unknown Interface
				return nil
			}
			ifName = rec.Ifname
			ifSpeed = rec.Ifspeed
			ponPort = rec.PonPort
			l1sp = rec.L1sp
		}
	}
	snmpVar := SnmpVar{
		CollectTime: JsonTime(collectTime),
		ObjType:     job.ObjType,
		RowId:       rowId,
		SnmpName:    name,
		SnmpValue:   val,
		RowIndex:    rowIndex,
		IfIndex:     ifIndex,
		IfName:      ifName,
		IfSpeed:     ifSpeed,
		OntId:       ontId,
		PonPort:     ponPort,
		L1sp:        l1sp,
	}
	return &snmpVar
}

func mapSnmpVar_OltUplink(job *SnmpBulkGetJob, target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {
	// Fiberhome: rowIndex = ??
	// Huawei:		rowIndex = {ifIndex}
	rowIndex := strings.Replace(variable.Name, snmpOid.Oid+".", "", 1)
	ifIndex := rowIndex

	val, err := ToValue(snmpOid, variable)
	if err != nil {
		log.Printf("Error! %s invalid value: %v", target.IP, variable)
		return nil
	}

	// trim space
	switch k := val.(type) {
	case string:
		val = strings.TrimSpace(k)
	}

	if target.Vendor == "Nokia" {
		if rowIndex == "257" {
			ifIndex = "131072"
		} else if rowIndex == "258" {
			ifIndex = "262144"
		}
	}
	// log.Printf("%v|%v|%v", rowIndex, snmpOid.Name, val)

	snmpVar := SnmpVar{
		CollectTime: JsonTime(collectTime),
		ObjType:     job.ObjType,
		SnmpName:    snmpOid.Name,
		SnmpValue:   val,
		RowId:       rowIndex,
		RowIndex:    rowIndex,
		IfIndex:     ifIndex,
		// IfName:      ifName,
		// IfSpeed:     ifSpeed,
		// OntId:       ontId,
		// PonPort:     ponPort,
		// L1sp:        l1sp,
	}
	return &snmpVar
}

func mapSnmpVar_OltPon(job *SnmpBulkGetJob, target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {
	// Fiberhome: rowIndex = ??
	// Huawei:		rowIndex = {ifIndex}
	rowIndex := strings.Replace(variable.Name, snmpOid.Oid+".", "", 1)
	ifIndex := rowIndex
	name := snmpOid.Name

	val, err := ToValue(snmpOid, variable)
	if err != nil {
		log.Printf("Error! %s invalid value: %v", target.IP, variable)
		return nil
	}

	// trim space
	switch k := val.(type) {
	case string:
		val = strings.TrimSpace(k)
	}

	if target.Vendor == "Nokia" {
		// mapping is done at transform stage

	} else if target.Vendor == "ZTE" {
		// olt-pon-zte1: ponport.ifindex = rowIndex
		// olt-pon-zte2: ponport.ponport = zte_olt_pon_rowId_to_PonPort(rowIndex)
		if job.Name == "olt-pon-zte2" {
			_, ponpontStr, wavelength, retcode := zte_olt_pon_rowId_to_PonPort(rowIndex)
			if retcode != 2 {
				return nil
			}

			ponport, ok := target.PonPortsName[ponpontStr]
			if ok {
				ifIndex = ponport.Ifindex
				rowIndex = ponport.Ifindex
			}
			// rename variable:
			// zte_pon_dual_txpwr   --> zte_pon_dual_txpwr{wavelength}
			// zte_pon_dual_current --> zte_pon_dual_current{wavelength}
			name = fmt.Sprintf("%s%s", name, wavelength)
		}
	}

	snmpVar := SnmpVar{
		CollectTime: JsonTime(collectTime),
		ObjType:     job.ObjType,
		SnmpName:    name,
		SnmpValue:   val,
		RowId:       rowIndex,
		RowIndex:    rowIndex,
		IfIndex:     ifIndex,
		// IfName:      ifName,
		// IfSpeed:     ifSpeed,
		// OntId:       ontId,
		// PonPort:     ponPort,
		// L1sp:        l1sp,
	}
	return &snmpVar
}

func mapSnmpVar_OnuPon(job *SnmpBulkGetJob, target *SnmpTarget, snmpOid *SnmpOid, collectTime time.Time, variable gosnmp.SnmpPDU) *SnmpVar {
	// Fiberhome: rowIndex = {rowId} where rowId is not related to ponport table
	// ZTE:       rowIndex = {ifIndex}.{ontId}
	// ZTE: 			rowIndex = {ifIndex}.{ontId}.1 	(oid: 1.3.6.1.4.1.3902.1082.500.20.2.2.2.1.{ifIndex}.{ontId}.1)
	// Huawei:		rowIndex = {ifIndex}.{ontId}
	// Nokia:			rowIndex = {ONT_IfIndex} which required sepcial decoder: GetOnuPonIdForNokia(ONT_IfIndex)
	varName := snmpOid.Name // default value set to snmpOid.Name, except hua_onu_in_pkterr and hau_onu_out_pkterr
	ifIndex := ""
	ifName := ""
	ponPort := ""
	ontId := ""
	rowIndex := strings.Replace(variable.Name, snmpOid.Oid+".", "", 1)

	if target.Vendor == "Fiberhome" {
		// ponIdx := rowIndex
		tokens := strings.Split(rowIndex, ".")
		if len(tokens) == 1 {
			slot, pon, ontid, ok := fbh_decode_ponIdx(tokens[0])
			if ok {
				ponPort = fmt.Sprintf("1-1-%s-%s", slot, pon)
				ontId = ontid
				rowIndex = fmt.Sprintf("%s.%s", ponPort, ontId)
			}
			// log.Printf("fbh: %s | %v | %v | %v | %v", snmpOid.Name, variable.Value, rowIndex, tokens, ponPort)

		} else if len(tokens) == 2 {
			slot, pon, ok := fbh_decode_ponIdx_no_ontId(tokens[0])
			if ok {
				ponPort = fmt.Sprintf("1-1-%s-%s", slot, pon)
				ontId = tokens[1]
				rowIndex = fmt.Sprintf("%s.%s", ponPort, ontId)
			}
			// log.Printf("fbh: %s | %v | %v | %v | %v", snmpOid.Name, variable.Value, rowIndex, tokens, ponPort)
		}

	} else if target.Vendor == "ZTE" {
		// ZTE:	rowIndex = {ifIndex}.{ontId}
		// ZTE: rowIndex = {ifIndex}.{ontId}.1
		tokens := strings.Split(rowIndex, ".")
		if len(tokens) >= 2 {
			rowIndex = fmt.Sprintf("%s.%s", tokens[0], tokens[1])
			ifIndex = tokens[0]
			ontId = tokens[1]
			ponPortObj, ok := target.PonPortsIfIndex[ifIndex]
			if ok {
				ponPort = ponPortObj.PonPort
				ifName = ponPortObj.Ifname
			}
		}

	} else if target.Vendor == "Huawei" {
		tokens := strings.Split(rowIndex, ".")
		if len(tokens) == 2 {
			ifIndex = tokens[0]
			ontId = tokens[1]
			ponPortObj, ok := target.PonPortsIfIndex[ifIndex]
			if ok {
				ponPort = ponPortObj.PonPort
				ifName = ponPortObj.Ifname
			}
		} else {
			// sepcial case for hua_onu_in_pkterr, hua_onu_out_pkterr
			// snmpbulkwalk -v2c -c public123 10.238.152.16 1.3.6.1.4.1.2011.6.128.1.1.4.25.1.45
			if snmpOid.Oid == ".1.3.6.1.4.1.2011.6.128.1.1.4.25.1.7" || snmpOid.Oid == ".1.3.6.1.4.1.2011.6.128.1.1.4.25.1.45" {
				if len(tokens) == 3 {
					// rename: hua_onu_in_pkterr 	--> hua_onu_in_pkterr1 ... hua_onu_in_pkterr4
					// renmae: hua_onu_out_pkterr --> hua_onu_out_pkterr1 .. hua_onu_out_pkterr4
					varName = fmt.Sprintf("%s%s", snmpOid.Name, tokens[2])
					rowIndex = fmt.Sprintf("%s.%s", tokens[0], tokens[1])
					ifIndex = tokens[0]
					ontId = tokens[1]
					ponPortObj, ok := target.PonPortsIfIndex[ifIndex]
					if ok {
						ponPort = ponPortObj.PonPort
						ifName = ponPortObj.Ifname
					}
					// log.Printf("hua=%s | %s | %s | %v", snmpOid.Name, rowIndex, varName, variable.Value)
				}
			}
		}

	} else if target.Vendor == "Nokia" {
		// <PON_ifIndex>.<ONT_ID>
		// snmpbulkwalk -v2c -c public 10.237.205.147 1.3.6.1.4.1.637.61.1.35.11.4.1.3
		// snmpbulkwalk -v2c -c public 10.237.205.147 1.3.6.1.4.1.637.61.1.35.11.4.1.4
		if strings.HasPrefix(variable.Name, ".1.3.6.1.4.1.637.61.1.35.11.4.1.3") || strings.HasPrefix(variable.Name, ".1.3.6.1.4.1.637.61.1.35.11.4.1.4") {
			tokens := strings.Split(rowIndex, ".")
			if len(tokens) == 2 {
				PON_ifIndex := tokens[0]
				ponPortObj, ok := target.PonPortsIfIndex[PON_ifIndex]
				if ok {
					ponPort = ponPortObj.PonPort
					ontId = tokens[1]
					rowIndex = fmt.Sprintf("%s.%s", ponPort, ontId)
				}
			}
		} else {
			// <XXX>.<ONT_ifIndex>
			// snmpbulkwalk -v2c -c public 10.237.205.147 1.3.6.1.4.1.637.61.1.35.11.22.1.5
			// <ONT_ifIndex>
			// snmpbulkwalk -v2c -c public 10.237.205.147 1.3.6.1.4.1.637.61.1.35.10.4.1.3
			// get last index for <ONT_ifIndex>
			tokens := strings.Split(rowIndex, ".")
			if len(tokens) > 0 {
				ONT_ifIndex := tokens[len(tokens)-1]
				ponPort, ontId = nok_decode_ONT_ifIndex(ONT_ifIndex)
				rowIndex = fmt.Sprintf("%s.%s", ponPort, ontId)
			}
		}
		// log.Printf("nok: %s | %v | %v | %v | %v", snmpOid.Name, variable.Value, rowIndex, ponPort, ontId)

	} else if target.Vendor == "Dasan" {
		// snmpbulkwalk -v2c -c public -On 10.178.153.20 1.3.6.1.4.1.6296.101.23.6.6.1.1.20
		// .1.3.6.1.4.1.6296.101.23.6.6.1.1.20.1.1.1 = STRING: "-20.9700"
		// .1.3.6.1.4.1.6296.101.23.6.6.1.1.20.1.2.1 = STRING: "-23.9800"
		// .1.3.6.1.4.1.6296.101.23.6.6.1.1.20.1.3.1 = STRING: "-22.0700"

		tokens := strings.Split(rowIndex, ".")
		if len(tokens) >= 2 {
			ifIndex = tokens[0]
			ontId = tokens[1]
		}
		ponPortObj, ok := target.PonPortsIfIndex[ifIndex]
		if ok {
			ponPort = ponPortObj.PonPort
			ifName = ponPortObj.Ifname
		}
		// log.Printf("dsn: %v|%v|%v|%v|%v|%v", varName, variable.Name, rowIndex, ifIndex, ponPort, ontId)
	}

	val, err := ToValue(snmpOid, variable)
	if err != nil {
		log.Printf("Error! %s invalid value: %v", target.IP, variable)
		return nil
	}

	snmpVar := SnmpVar{
		CollectTime: JsonTime(collectTime),
		ObjType:     job.ObjType,
		SnmpName:    varName,
		SnmpValue:   val,
		RowId:       rowIndex,
		RowIndex:    rowIndex,
		IfIndex:     ifIndex,
		OntId:       ontId,
		PonPort:     ponPort,
		IfName:      ifName,
	}

	// s, _ := json.MarshalIndent(snmpVar, "", " ")
	// log.Printf("%s", s)
	return &snmpVar
}

func GetOltPonIdForNokia(ifIndex string) string {
	ifIndex_Int, err := strconv.Atoi(ifIndex)
	if err != nil {
		return ""
	}
	val := ((ifIndex_Int - 60817408) / 65536) + 1
	if val > 0 && val <= 32 {
		return fmt.Sprintf("%d", val)
	}
	return ""
}

func nok_decode_ONT_ifIndex(ONT_IfIndex string) (string, string) {
	// ONT_IfIndex = 62914560 + (PON_ID - 1)*65536 + (ONT_ID - 1)*512
	ONT_IfIndex_Int, err := strconv.Atoi(ONT_IfIndex)
	if err != nil {
		return "", ""
	}
	val1 := ONT_IfIndex_Int - 62914560
	for pon_id := 1; pon_id <= 10; pon_id++ {
		for ont_id := 1; ont_id <= 128; ont_id++ {
			val2 := ((pon_id - 1) * 65536) + ((ont_id - 1) * 512)
			if val1 == val2 {
				ponPort := fmt.Sprintf("1-1-1-%d", pon_id)
				return ponPort, strconv.Itoa(ont_id)
			}
		}
	}
	return "", ""
}

func fbh_onu_ifname(onuIfName string) (string, string) {
	// input: fbh onu ifname
	// return: (ponport and ontid)
	// snmpbulkwalk -v2c -c adsl 10.237.153.6 1.3.6.1.4.1.5875.800.3.9.3.3.1.2
	// SNMPv2-SMI::enterprises.5875.800.3.9.3.3.1.2.34078976 = STRING: "PON 1/1/1"
	// SNMPv2-SMI::enterprises.5875.800.3.9.3.3.1.2.34079232 = STRING: "PON 1/1/2"
	ponPort := ""
	onuId := ""
	re := regexp.MustCompile(`^PON (\d+)\/(\d+)\/(\d+)$`)
	m := re.FindStringSubmatch(onuIfName)
	if m != nil {
		ponPort = "1-1-" + m[1] + "-" + m[2]
		onuId = m[3]
	}
	return ponPort, onuId
}

func fbh_decode_ponIdx(ponIdx string) (string, string, string, bool) {
	// input: ponIdx
	// return: (slot, pon)
	// snmpbulkwalk -v2c -c adsl 10.237.153.6 1.3.6.1.4.1.5875.800.3.9.3.7.1.2
	// SNMPv2-SMI::enterprises.5875.800.3.9.3.7.1.2.34078720.1 = INTEGER: -1850
	// SNMPv2-SMI::enterprises.5875.800.3.9.3.7.1.2.34078720.2 = INTEGER: -1974
	// ---
	// Formula: (slot x 33554432) + (pon x 524288) = 34078720
	// const SLOT_MULT = 33554432
	// const PON_MULT = 524288

	// if ponIdx%PON_MULT != 0 {
	// 	return 0, 0, false // No solution
	// }

	// pon := (ponIdx % SLOT_MULT) / PON_MULT
	// slot := (ponIdx - (pon * PON_MULT)) / SLOT_MULT
	// return slot, pon, true

	val, err := strconv.Atoi(ponIdx)
	if err != nil {
		return "", "", "", false
	}
	slot := val / 33554432
	pon := (val - slot*33554432) / 524288
	ontid := (val - slot*33554432 - pon*524288) / 256
	return strconv.Itoa(slot), strconv.Itoa(pon), strconv.Itoa(ontid), true
}

func fbh_decode_ponIdx_no_ontId(ponIdx string) (string, string, bool) {
	val, err := strconv.Atoi(ponIdx)
	if err != nil {
		return "", "", false
	}
	slot := val / 33554432
	pon := (val - slot*33554432) / 524288
	return strconv.Itoa(slot), strconv.Itoa(pon), true
}

func zte_olt_pon_rowId_to_PonPort(rowId string) (string, string, string, int) {
	// return (ifindex, ponport, channel, retcode)
	// There're 2 possible response
	// 	1.) single wavelength: rowId = 285278977	--> type != "0101"	--> do not try to convert --> use rowId as ifIndex --> return retcode = 1
	//	2.) dual wavelength:   rowId = 1360052481	--> type = "0101"  	--> convert --> return retcode = 2
	// 	3.) convert failed --> return retcode = -1
	// 			ponport = 1-1-3-1, wavelength = 1490 or 1577
	// --- decode ---
	// 0101	 			= 5 	type
	// 0001 			= 1 	rack
	// 0001 			= 1 	shelf
	// 000001 		= 1 	slot
	// 001000 	  = 8 	port
	// 00000001  	= 1 	channel
	num, err := strconv.ParseInt(rowId, 10, 32)
	if err != nil {
		return "", "", "", -1
	}
	binaryStr := fmt.Sprintf("%032b", uint32(num))
	typeStr := binaryStr[:4]
	rackStr := binaryStr[4:8]
	shelfStr := binaryStr[8:12]
	slotStr := binaryStr[12:18]
	portStr := binaryStr[18:24]
	channelStr := binaryStr[24:]
	if typeStr != "0101" {
		// do not convert, use rowId as ifIndex
		return rowId, "", "", 1
	}

	rack, _ := strconv.ParseInt(rackStr, 2, 32)
	shelf, _ := strconv.ParseInt(shelfStr, 2, 32)
	slot, _ := strconv.ParseInt(slotStr, 2, 32)
	port, _ := strconv.ParseInt(portStr, 2, 32)
	channel, _ := strconv.ParseInt(channelStr, 2, 32)
	ponport := fmt.Sprintf("%d-%d-%d-%d", rack, shelf, slot, port)
	wavelength := ""
	if channel == 1 {
		wavelength = "1490"
		return "", ponport, wavelength, 2
	} else if channel == 2 {
		wavelength = "1577"
		return "", ponport, wavelength, 2
	}
	// log.Printf("zte_olt_pon_ifindex: %-10v | %v | rack=%v | shelf=%v | slot=%v | port=%v | channel=%v | %s", rowId, binaryStr, rack, shelf, slot, port, channel, ponport)
	return "", "", "", -1
}
