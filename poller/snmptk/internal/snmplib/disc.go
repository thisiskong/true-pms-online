package snmplib

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode"

	_ "github.com/lib/pq"
)

func lookupTopologyByIpAddr(ip2Topology *map[string]string, ifalias string) (string, string) {
	// extract ip addr from ifalias and lookup from ip2Topology
	re := regexp.MustCompile(`.*[-_](?P<ipaddr>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})([^\d])?.*`)
	m := re.FindAllStringSubmatch(ifalias, -1)
	if m != nil {
		ipaddr := m[0][1]
		iftopology, ok := (*ip2Topology)[ipaddr]
		if ok {
			// log.Printf("lookupTopologyByIpAddr: %v = %v, %v", ifalias, ipaddr, iftopology)
			return ipaddr, iftopology
		} else {
			// log.Printf("lookupTopologyByIpAddr: %v = %v, %v", ifalias, ipaddr, "")
			return "", ""
		}
	}
	// log.Printf("lookupTopologyByIpAddr: %v = %v, %v", ifalias, "", "")
	return "", ""
}

type DiscMetric struct {
	id      string // disc.id
	success int    // number of success IP
	failed  int    // number of failed IP
}

func NewDiscoveryProcessor(task *DiscoveryConfig, wg *sync.WaitGroup, tasksDone chan SnmpResult) error {
	start := time.Now()
	defer wg.Done()

	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable&connect_timeout=10"
	db, err := sql.Open("postgres", task.Setting.DbConnection)
	if err != nil {
		log.Panic(err)
	}
	defer db.Close()

	// lookup service
	lookupService, err := NewLookupService(task)
	if err != nil {
		log.Panic(err)
	}

	// lldp mapper
	lldpMapper := NewLldpMapper(task, lookupService)

	ptime := time.Now()
	cnt_ok := 0
	cnt_err := 0
	cnt_target := 0
	cnt_map := make(map[string]*DiscMetric)
	for _, disc := range task.Discovery.Discoveries {
		cnt_target = cnt_target + len(disc.SnmpTargets)
	}
	for i := 0; i < cnt_target; i++ {
		snmpResult, ok := <-tasksDone
		if !ok {
			// channel was closed
			log.Fatal("Error: channel is closed")
		}

		// log result
		logTarget(snmpResult)

		rec, ok := cnt_map[snmpResult.Discovery.Id]
		if !ok {
			rec = &DiscMetric{id: snmpResult.Discovery.Id}
			cnt_map[snmpResult.Discovery.Id] = rec
		}

		if snmpResult.Error != "" || snmpResult.SnmpVars == nil || snmpResult.Device == nil {
			cnt_err++
			rec.failed++
			continue
		}
		cnt_ok++
		rec.success++

		deviceInst := snmpResult.Device
		saveDeviceInstance(db, deviceInst, ptime)
	}

	log.Printf("Completed: %d total, %d success, %d error in %s", cnt_target, cnt_ok, cnt_err, time.Since(start))

	// update lldp from OLT to uplink device
	err = lldpMapper.update_lldp_uplink(db)
	if err != nil {
		log.Printf("Error! %v", err)
	}

	// update to db
	tx, err := db.Begin()
	if err != nil {
		log.Printf("Error! %v", err)
		return err
	}

	for _, rec := range cnt_map {
		log.Printf("update disc: id=%s, success=%d, failed=%d", rec.id, rec.success, rec.failed)
		tx.Exec("update disc set lastrun=$1, success=$2, error=$3 where id=$4", ptime, rec.success, rec.failed, rec.id)
	}

	tx.Commit()
	return nil
}

func saveDeviceInstance(db *sql.DB, deviceInst *Device, ptime time.Time) {
	ptime_str := ptime.Format("2006-01-02 15:04:05")

	// Begin Tx
	tx, err := db.Begin()
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}

	// save device
	last_err_sql, err := saveDevice(tx, deviceInst, ptime)
	if err != nil {
		tx.Rollback()
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error !%v", err)
	}

	// map dn & cpe
	last_err_sql, err = update_device_mapping(tx, deviceInst)
	if err != nil {
		tx.Rollback()
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error! %v", err)
	}

	// save interfaces
	last_err_sql, err = saveIntf(tx, deviceInst, ptime_str)
	if err != nil {
		tx.Rollback()
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error! %v", err)
	}

	// save intf_rev, ponport_rev
	last_err_sql, err = saveIntfRev(tx, deviceInst, ptime)
	if err != nil {
		tx.Rollback()
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error! %v", err)
	}

	// save card
	last_err_sql, err = saveBoards(tx, deviceInst, ptime_str)
	if err != nil {
		tx.Rollback()
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error! %v", err)
	}

	// update uplinkIp, uplinkSite, uplinkModel
	last_err_sql, err = update_device_uplink(tx, deviceInst)
	if err != nil {
		log.Printf("Error! sql=%v", last_err_sql)
		log.Fatalf("Error! %v", err)
	}

	// update lldp from OLT --> CPE for GCOM & Raisecome

	// Commit
	err = tx.Commit()
	if err != nil {
		log.Printf("Error! %v", err)
	}
}

func (snmpResult *SnmpResult) getSnmpValue(name string) string {
	for _, snmpVar := range *snmpResult.SnmpVars {
		// log.Printf("%v = %v", snmpVar.Name, snmpVar.Value)
		if snmpVar.Name == name {
			if snmpVar.Value != nil {
				return snmpVar.Value.(string)
			} else {
				return ""
			}
		}
	}
	return ""
}

func mapSysDescr(disc *DiscoveryTask, sysDescr string, hwSysVersion string) string {
	// return descr, vendor, model
	// remove leading, trailling "\r\n"
	// replace "\r\n" with "|"
	var descr string
	// var vendor string
	// var model string
	lines := make([]string, 0)
	for _, line := range strings.Split(strings.Trim(sysDescr, "\r\n"), "\r\n") {
		lines = append(lines, strings.TrimSpace(line))
	}
	if hwSysVersion != "" {
		lines = append(lines, strings.TrimSpace(hwSysVersion))
	}
	descr = strings.Join(lines, "|")
	return descr
}

func logTarget(snmpResult SnmpResult) {
	ip := snmpResult.Target.IP
	agent := snmpResult.Target.Agent
	status := "Ok"
	if snmpResult.Error != "" {
		status = snmpResult.Error
	}
	hostname, _ := os.Hostname()
	log.Printf("Discovery|%s|%s|%s|%s|%s|%s", hostname, ip, snmpResult.Target.Network, snmpResult.Target.Topology, agent, status)
}

func update_device_mapping(tx *sql.Tx, deviceInst *Device) (string, error) {
	// clear fields
	sql := `update device set
                  ringid 				= null,
                  ringtopo 			= null,
                  hop 					= null,
                  rn 						= null,
									pn 						= null,
									dn						= null,
                  region 				= null,
                  a_homing_id 	= null,
                  a_homing_site = null,
                  b_homing_id 	= null,
                  b_homing_site = null,
                  c_homing_id 	= null,
                  c_homing_site = null,
                  uplink_ip1 		= null,
                  uplink_ip2 		= null,
                  uplink_site1 	= null,
                  uplink_site2 	= null,
                  uplink_model1 = null,
                  uplink_model2 = null
			where id = $1`
	stmt1, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt1.Close()
	ret, err := stmt1.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ := ret.RowsAffected()
	log.Printf("update_device_mapping: reset values %d rows", cnt)

	// dn
	sql = `update device
					set ringid 		= v_dn_map.ringid,
							ringtopo 	= v_dn_map.ringtopo,
							hop 			= v_dn_map.hop,
							rn 				= v_dn_map.rn,
							pn 				= v_dn_map.pn,
							region 		= v_dn_map.region
				from v_dn_map
				where device.id = $1 and (device.ip = v_dn_map.ip1 or device.ip = v_dn_map.ip2)`
	stmt2, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt2.Close()
	ret, err = stmt2.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ = ret.RowsAffected()
	log.Printf("update_device_mapping: dn %d rows", cnt)

	// cpe
	sql = `update device
					set ringid 					= v_cpe_map.ringid,
							ringtopo 				= v_cpe_map.ringtopo,
							hop 						= v_cpe_map.hop,
							a_homing_id 		= v_cpe_map.a_homing_id,
							a_homing_site 	= v_cpe_map.a_homing_site,
							b_homing_id			= v_cpe_map.b_homing_id,
							b_homing_site 	= v_cpe_map.b_homing_site,
							c_homing_id			= v_cpe_map.c_homing_id,
							c_homing_site 	= v_cpe_map.c_homing_site,
							rn 							= v_cpe_map.rn,
							pn 							= v_cpe_map.pn,
							dn 							= v_cpe_map.dn,
							region 					= v_cpe_map.region,
							uplink_ip1			= v_cpe_map.uplink_ip1,
							uplink_ip2			= v_cpe_map.uplink_Ip2
					from v_cpe_map
					where device.id = $1 and device.ip = v_cpe_map.ip`
	stmt3, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt3.Close()
	ret, err = stmt3.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ = ret.RowsAffected()
	log.Printf("update_device_mapping: cpe %d rows", cnt)

	// OLT
	if deviceInst.Topology == "OLT" {
		sql = `with x as (
							select distinct device,
															ringid,
															ringtopo,
															hop,
															a_homing_id,
															a_homing_site,
															b_homing_id,
															b_homing_site,
															c_homing_id,
															c_homing_site,
															rn,
															pn,
															dn,
															region,
															sitename,
															uplink_ip1,
															uplink_Ip2
							from v_access_ringinfo
							where pollstatus = 1 and device = $1
					)
					update device set
							ringid 					= x.ringid,
							ringtopo 				= x.ringtopo,
							hop 						= x.hop,
							a_homing_id     = x.a_homing_id,
							a_homing_site   = x.a_homing_site,
							b_homing_id			= x.b_homing_id,
							b_homing_site   = x.b_homing_site,
							c_homing_id			= x.c_homing_id,
							c_homing_site   = x.c_homing_site,
							rn 							= x.rn,
							pn 							= x.pn,
							dn 							= x.dn,
							region 					= x.region,
							sitename        = x.sitename,
							uplink_ip1			= x.uplink_ip1,
							uplink_ip2			= x.uplink_Ip2
					from x where device.id = $2 and device.name = x.device`
		stmt4, err := tx.Prepare(sql)
		if err != nil {
			return sql, err
		}
		defer stmt4.Close()
		ret, err = stmt4.Exec(deviceInst.SysName, deviceInst.DeviceId)
		if err != nil {
			return sql, err
		}
		cnt, _ = ret.RowsAffected()
		log.Printf("update_device_mapping: v_access_ringinfo %d rows", cnt)
	}
	return "", nil
}

func update_device_uplink(tx *sql.Tx, deviceInst *Device) (string, error) {
	// clear existing values
	sql := `update device
						set uplink_site1 	= null,
							uplink_model1 	= null,
							uplink_site2 		= null,
							uplink_model2 	= null
						where id = $1`
	stmt1, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt1.Close()
	ret, err := stmt1.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ := ret.RowsAffected()
	log.Printf("update_device_uplink: reset values %d rows", cnt)

	// uplink_site1, uplink_model1
	sql = `update device d1
					set uplink_site1  = d2.sitename,
					    uplink_model1 = d2.model
					from (
							select id, ip, model, sitename, rownum from (
								select id, ip, model, sitename, row_number() over (partition by ip order by lastseen desc) as rownum
								from device
								) x where rownum = 1
					) d2 where (d1.uplink_ip1 = d2.ip) and d1.id = $1`
	stmt2, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt2.Close()
	ret, err = stmt2.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ = ret.RowsAffected()
	log.Printf("update_device_uplink: set uplink_site1 %d rows", cnt)

	// uplink_site2, uplink_model2
	sql = `update device d1
					set uplink_site2  = d2.sitename,
						uplink_model2 	= d2.model
					from (
							select id, ip, model, sitename, rownum from (
								select id, ip, model, sitename, row_number() over (partition by ip order by lastseen desc) as rownum
								from device
								) x where rownum = 1
					) d2 where (d1.uplink_ip2 = d2.ip) and d1.id = $1`
	stmt3, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}
	defer stmt3.Close()
	ret, err = stmt3.Exec(deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	cnt, _ = ret.RowsAffected()
	log.Printf("update_device_uplink: set uplink_site2 %d rows", cnt)
	return "", nil
}

func logDevice(device *Device) {
	s, _ := json.MarshalIndent(*device, "", " ")
	log.Printf("device = %s", string(s))
}

func snmp2Device(snmpResult *SnmpResult, task *DiscoveryConfig,
	mapper *Mapper,
	lldpMapper *LldpMapper,
	lookupService *LookupService) (*Device, error) {

	if debug {
		s, _ := json.MarshalIndent(snmpResult.SnmpVars, "", " ")
		log.Printf("snmpVars = %s", s)
	}

	// Device
	deviceIp := snmpResult.Target.IP
	sysName := snmpResult.getSnmpValue("sysName")
	sysDescr := snmpResult.getSnmpValue("sysDescr")
	sysObjectID := snmpResult.getSnmpValue("sysObjectID")
	lldpLocChassisId := GetLldpChassisId(snmpResult)
	swVersion := GetSwVersion(snmpResult)

	if !snmpResult.SaveDevice {
		return nil, fmt.Errorf("discovery disable: ip=%v, sysDescr=%v", deviceIp, sysDescr)
	}

	if sysName == "" {
		return nil, fmt.Errorf("invalid device: sysName is blank, ip=%v", deviceIp)
	}

	if sysDescr == "" {
		return nil, fmt.Errorf("invalid device: sysDescr is blank, ip=%v", deviceIp)
	}

	// format sysDescr
	descr := mapSysDescr(task.Discovery, sysDescr, swVersion)
	model := GetDeviceModel(snmpResult)

	// var discAgent, discId string
	// var discPollInt int
	// var pollStatus int64 = 0
	// if snmpResult.Discovery != nil {
	// 	discAgent = snmpResult.Discovery.Agent
	// 	discId = snmpResult.Discovery.Id
	// 	if snmpResult.Discovery.PollInt != nil {
	// 		discPollInt = *snmpResult.Discovery.PollInt
	// 	}
	// 	if snmpResult.Discovery.PollStatus {
	// 		pollStatus = 1
	// 	}
	// }

	deviceInst := Device{
		DeviceIp:    deviceIp,
		ChassisId:   lldpLocChassisId,
		SysName:     sysName,
		SysDescr:    sysDescr,
		SysObjectID: sysObjectID,
		Network:     snmpResult.Target.Network,
		Topology:    snmpResult.Target.Topology,
		Community:   snmpResult.Target.Community,
		Descr:       descr,
		Vendor:      "",
		Model:       model,
		SwVersion:   swVersion,
		Sitename:    "",
		// Agent:            discAgent,
		// DiscoveryId:      discId,
		// DiscoveryPollInt: discPollInt,
		// PollStatus:       pollStatus,
	}

	// device.Province
	mapper.SetProvince(&deviceInst, &lookupService.ProvinceCode)

	// set discovery fields
	mapper.SetDiscoveryFields(&deviceInst, snmpResult.Discovery)

	// map device
	mapper.MapDevice(&deviceInst)

	// lookup disc_device_info using device name to get model & swversion
	// for OLT GCOM
	if deviceInst.Network == "FTTx" && deviceInst.Vendor == "GCOM" {
		lookupService.mapDiscDeviceInfo(&deviceInst)
	}

	// // ipAddrTable
	// ipAddrTableLookup := make(map[string]string)
	// ipAddrTable, ok := snmpResult.SnmpTables["ipAddrTable"]
	// if ok && ipAddrTable.Error == "" {
	// 	for _, row := range ipAddrTable.Entries {
	// 		ipAdEntAddr := row.Values["ipAdEntAddr"]
	// 		ipAdEntIfIndex := row.Values["ipAdEntIfIndex"]
	// 		if ipAdEntAddr != nil && ipAdEntIfIndex != nil {
	// 			ipaddr := ipAdEntAddr.Value.(string)
	// 			ifindex := fmt.Sprintf("%d", ipAdEntIfIndex.Value.(int64))
	// 			ipAddrTableLookup[ifindex] = ipaddr
	// 		}
	// 	}
	// }

	// Interfaces
	ifTable, ok := snmpResult.SnmpTables["ifTable"]
	if !ok {
		return &deviceInst, fmt.Errorf("ifTable missing")
	}
	if ifTable.Error != "" {
		return &deviceInst, fmt.Errorf("ifTable error: %v", ifTable.Error)
	}

	deviceInst.Interfaces = make([]*Interface, 0, len(ifTable.Entries))
	for _, intf := range ifTable.Entries {
		ifIndex := intf.Values["ifIndex"]
		ifName := intf.Values["ifName"]
		ifDescr := intf.Values["ifDescr"]
		ifAlias := intf.Values["ifAlias"]
		ifSpeed := intf.Values["ifSpeed"]
		ifHighSpeed := intf.Values["ifHighSpeed"]
		ifType := intf.Values["ifType"]
		ifPhysAddress := intf.Values["ifPhysAddress"]
		ifAdmin := intf.Values["ifAdminStatus"]
		ifOper := intf.Values["ifOperStatus"]
		ifConnector := intf.Values["ifConnectorPresent"]

		// CR2024: if ifalias = nil, set to blank ""
		// CR2024: if ifname = nil, set to blank ""
		ifindex := ""
		ifalias := ""
		ifname := ""
		ifphysaddr := ""

		if ifIndex == nil || ifIndex.Value == nil {
			log.Printf("Error! Invalid Intf: [%v] IfIndex is nil", deviceIp)
			continue
		} else {
			ifindex = fmt.Sprintf("%d", ifIndex.Value.(int64))
		}
		// CR2024: allow ifName.value = nil (Nokia OLT)
		if ifName == nil || ifName.Value == nil {
			ifname = ""
			// log.Printf("Error! Invalid Intf: [%v:%v] ifName is nil", deviceIp, ifIndex)
			// continue
		} else {
			ifname = ifName.Value.(string)
		}
		if ifDescr == nil || ifDescr.Value == nil {
			log.Printf("Error! Invalid Intf: [%v:%v] ifDescr is nil", deviceIp, ifIndex)
			continue
		}
		// CR2024: allow ifAlias.value = nil
		if ifAlias == nil || ifAlias.Value == nil {
			ifalias = ""
			// log.Printf("Error! Invalid Intf: [%v:%v] ifAlias is nil", deviceIp, ifIndex)
			// continue
		} else {
			ifalias = ifAlias.Value.(string)
		}
		// CR2024: OLT Nokia not support ifHighSpeed
		if ifHighSpeed == nil || ifHighSpeed.Value == nil {
			log.Printf("Warn! Invalid Intf: [%v:%v] ifHighSpeed is nil", deviceIp, ifIndex)
			// log.Printf("Error! Invalid Intf: [%v:%v] ifHighSpeed is nil", deviceIp, ifIndex)
			// continue
		}
		if ifType == nil || ifType.Value == nil {
			log.Printf("Error! Invalid Intf: [%v:%v] ifType is nil", deviceIp, ifIndex)
			continue
		}
		if ifPhysAddress == nil || ifPhysAddress.Value == nil {
			ifphysaddr = ""
			// log.Printf("Error! Invalid Intf: [%v:%v] ifPhysAddress is nil", deviceIp, ifIndex)
			// continue
		} else {
			ifphysaddr = ifPhysAddress.Value.(string)
		}
		if ifAdmin == nil || ifAdmin.Value == nil {
			log.Printf("Error! Invalid Intf: [%v:%v] ifAdmin is nil", deviceIp, ifIndex)
			continue
		}
		if ifOper == nil || ifOper.Value == nil {
			log.Printf("Error! Invalid Intf: [%v:%v] ifOper is nil", deviceIp, ifIndex)
			continue
		}

		ifname = RemoveInvalidCharacter(ifname)
		ifdescr := RemoveInvalidCharacter(ifDescr.Value.(string))
		ifalias = RemoveInvalidCharacter(ifalias)
		iftype := ifType.Value.(string)
		ifspeed := GetIfSpeed(ifHighSpeed, ifSpeed, deviceInst)
		ifdstip, iftopology := lookupTopologyByIpAddr(&lookupService.Ip2Topology, ifalias)

		var ifconn int64
		if ifConnector != nil {
			ifconn = ifConnector.Value.(int64)
		}

		intf := Interface{
			IfIndex:    ifindex,
			IfName:     ifname,
			IfDescr:    ifdescr,
			IfAlias:    ifalias,
			IfTopology: iftopology,
			IfDstIp:    ifdstip,
			IfType:     iftype,
			IfPhyAddr:  ifphysaddr,
			IfConn:     ifconn,
			IfSpeed:    ifspeed,
			IfAdmin:    ifAdmin.Value.(string),
			IfOper:     ifOper.Value.(string),
			DstName:    "",
			DstPort:    "",
			Save:       true,
		}
		deviceInst.Interfaces = append(deviceInst.Interfaces, &intf)
	}

	// lldp
	lldpMapper.mapLldp(&deviceInst, snmpResult)

	// FTTx (before mapping.js)
	if deviceInst.Network == "FTTx" {
		// Set OLT DstSite (For Nokia only)
		set_fttx_intf_dstsite(task, &snmpResult.Target, &deviceInst)
	}

	// mapper
	mapper.MapIntfs(&deviceInst)

	// FTTx (after mapping.js)
	if deviceInst.Network == "FTTx" {
		// Set L1 Splitter
		MapL1Splitter(task, lookupService, &deviceInst)

		// Set OLT Uplink moduleclass & vendorPn
		set_fttx_intf_moduleclass(task, &snmpResult.Target, &deviceInst)

		// Set OLT PonPort moduleclass & vendorPn
		set_fttx_ponport_moduleclass(task, &snmpResult.Target, &deviceInst)

		// // Set OLT PonPort cardtype
		// set_fttx_ponport_cardtype(task, &snmpResult.Target, &deviceInst)

		// Board
		set_fttx_board(task, &snmpResult.Target, &deviceInst, mapper)
	}

	// FTTx - Set ponport.moduleclass
	return &deviceInst, nil
}

func saveDevice(tx *sql.Tx, deviceInst *Device, ptime time.Time) (string, error) {
	// There's a case when update existing device with following scenario
	// 	IP				ChassisId				State
	//	--------------------------------------------------
	//	10.177.152.52	'' or NULL				Existing
	//	10.177.152.52	'00:0e:5e:00:46:fa'		New
	//
	// update chassisid=<new_value> if only one device with given IP and existing chassisid='' or chassid is null
	if len(deviceInst.ChassisId) > 0 {
		sql := fmt.Sprintf(`select id from device where (chassisid='' or chassisid is null) and ip='%s'`, deviceInst.DeviceIp)
		rows, err := tx.Query(sql)
		if err != nil {
			return sql, err
		}
		cnt := 0
		var device_id int64
		for rows.Next() {
			cnt++
			rows.Scan(&device_id)
		}
		defer rows.Close()

		if cnt == 1 {
			log.Printf("update device: %d, ip=%s, chassisId=%s", device_id, deviceInst.DeviceIp, deviceInst.ChassisId)
			sql = fmt.Sprintf(`update device set chassisid='%s' where id=%d`, deviceInst.ChassisId, device_id)
			_, err = tx.Exec(sql)
			if err != nil {
				return sql, err
			}
		}
	}

	// device table
	log.Printf("%v|%v|%v", deviceInst.ChassisId, deviceInst.Latitude, deviceInst.Longitude)
	sql := `INSERT INTO device(
				id, ip, chassisid,
				community, name, descr,
				vendor, model, swversion, network, topology, sitename,
				province, pollint, sys_pollstatus,
				disc_id, agent, first, lastseen,
				olttype, latitude, longitude)
			VALUES(
				NEXTVAL('device_seq'),
				$1,
				$2,
				$3,
				NULLIF($4, ''),
				$5,
				$6,
				NULLIF($7, ''),
				NULLIF($8, ''),
				NULLIF($9, ''),
				NULLIF($10, ''),
				NULLIF($11, ''),
				NULLIF($12, ''),
				$13,
				$14,
				$15,
				NULLIF($16, ''),
				$17,
				$18,
				NULLIF($19, ''),
				NULLIF($20, 0.0),
				NULLIF($21, 0.0)
			)
			ON CONFLICT (ip, chassisid) DO UPDATE
			SET
				community 			= EXCLUDED.community,
				name						= EXCLUDED.name,
				descr						= EXCLUDED.descr,
				vendor					= NULLIF(EXCLUDED.vendor, ''),
				model						= NULLIF(EXCLUDED.model, ''),
				swversion				= NULLIF(EXCLUDED.swversion, ''),
				network					= NULLIF(EXCLUDED.network, ''),
				topology				= NULLIF(EXCLUDED.topology, ''),
				sitename				= NULLIF(EXCLUDED.sitename, ''),
				province				= NULLIF(EXCLUDED.province, ''),
				pollint					= EXCLUDED.pollint,
				sys_pollstatus	= EXCLUDED.sys_pollstatus,
				disc_id					= EXCLUDED.disc_id,
				agent						= NULLIF(EXCLUDED.agent, ''),
				lastseen				= EXCLUDED.lastseen,
				olttype					= NULLIF(EXCLUDED.olttype, ''),
				latitude				= NULLIF(EXCLUDED.latitude, 0.0),
				longitude				= NULLIF(EXCLUDED.longitude, 0.0)
			RETURNING id`
	stmt, err := tx.Prepare(sql)
	if err != nil {
		return sql, err
	}

	disc_id, _ := strconv.ParseInt(deviceInst.DiscoveryId, 10, 64)
	err = stmt.QueryRow(
		deviceInst.DeviceIp,
		deviceInst.ChassisId,
		deviceInst.Community,
		deviceInst.SysName,
		deviceInst.Descr,
		deviceInst.Vendor,
		deviceInst.Model,
		deviceInst.SwVersion,
		deviceInst.Network,
		deviceInst.Topology,
		deviceInst.Sitename,
		deviceInst.Province,
		deviceInst.DiscoveryPollInt,
		deviceInst.PollStatus,
		disc_id,
		deviceInst.Agent,
		ptime,
		ptime,
		deviceInst.OltType,
		deviceInst.Latitude,
		deviceInst.Longitude).Scan(&deviceInst.DeviceId)
	if err != nil {
		return sql, err
	}
	return "", nil
}

func saveIntf(tx *sql.Tx, deviceInst *Device, ptime_str string) (string, error) {
	// Interfaces
	intfs := make([]string, 0)
	ponports := make([]string, 0)
	for _, intf := range deviceInst.Interfaces {
		if intf.Save {
			if intf.PonPort == "" {
				// intf
				ifid := fmt.Sprintf("%d.%s", deviceInst.DeviceId, intf.IfIndex)
				intfs = append(intfs, fmt.Sprintf(`(
							'%v', '%v', %d,   '%v',
							'%v', '%v', '%v', '%v',
							'%v', '%v', %v,   '%v',
							'%v', '%v', %v,
							nullif('%v', ''), nullif('%v', ''), nullif('%v', ''), nullif('%v', ''),
							nullif('%v', ''), nullif('%v', ''),
							nullif('%v', ''), nullif('%v', ''), nullif('%v', ''), nullif('%v', ''), nullif('%v', ''),
							%v, '%v', '%v')`,
					ifid, deviceInst.SysName, deviceInst.DeviceId, deviceInst.DeviceIp,
					intf.IfIndex, intf.Name, intf.IfName, intf.IfDescr,
					intf.IfAlias, intf.IfPhyAddr, intf.IfSpeed, intf.IfType,
					intf.IfAdmin, intf.IfOper, intf.IfConn,
					intf.DstName, intf.DstPort, intf.DstSite, intf.RemDstSite, intf.DstType, intf.MediaType,
					intf.DstSite2, intf.DstType2, intf.VendorPn, intf.ModuleClass, intf.AltName,
					intf.PollStatus, ptime_str, ptime_str))
			} else {
				// ponport
				ifid := fmt.Sprintf("%d.%s", deviceInst.DeviceId, intf.IfIndex)
				ponports = append(ponports, fmt.Sprintf(`(
							'%v', '%v', %d,   '%v',
							'%v', '%v', '%v', '%v',
							'%v', '%v', %v,   '%v',
							'%v', '%v', %v,   nullif('%v', ''), nullif('%v', ''),
							nullif('%v', ''), nullif('%v', ''), nullif('%v', '')::bigint, nullif('%v', '')::bigint,
							nullif('%v', ''), nullif('%v', ''),
							%v, '%v', '%v')`,
					ifid, deviceInst.SysName, deviceInst.DeviceId, deviceInst.DeviceIp,
					intf.IfIndex, intf.Name, intf.IfName, intf.IfDescr,
					intf.IfAlias, intf.IfPhyAddr, intf.IfSpeed, intf.IfType,
					intf.IfAdmin, intf.IfOper, intf.IfConn, intf.VendorPn, intf.ModuleClass,
					intf.PonPort, intf.L1_SPLT, intf.L1_DL_MAX_BW, intf.L1_UL_MAX_BW,
					intf.DL_BW_REMAINING, intf.UL_BW_REMAINING,
					intf.PollStatus, ptime_str, ptime_str))
			}
		}
	}

	// intfs
	if len(intfs) > 0 {
		sql := fmt.Sprintf(`INSERT INTO intf(
								id, device_name, device_id, device_ip,
								ifindex, name, ifname, ifdescr,
								ifalias, ifphyaddr, ifspeed, iftype,
								ifadmin, ifoper, ifconn, dstname,
								dstport, dstsite, remdstsite, dsttype,
								mediatype, dstsite2, dsttype2,
								vendorpn, moduleclass, altname,
								sys_pollstatus, first, lastseen)
							VALUES %v
							ON CONFLICT (id) DO UPDATE
							SET device_name=EXCLUDED.device_name, device_id=EXCLUDED.device_id, device_ip=EXCLUDED.device_ip,
									ifindex=EXCLUDED.ifindex, name=EXCLUDED.name, ifname=EXCLUDED.ifname, ifdescr=EXCLUDED.ifdescr,
									ifalias=EXCLUDED.ifalias, ifphyaddr=EXCLUDED.ifphyaddr, ifspeed=EXCLUDED.ifspeed, iftype=EXCLUDED.iftype,
									ifadmin=EXCLUDED.ifadmin, ifoper=EXCLUDED.ifoper, ifconn=EXCLUDED.ifconn, dstname=nullif(EXCLUDED.dstname, ''),
									dstport=nullif(EXCLUDED.dstport, ''), dstsite=nullif(EXCLUDED.dstsite, ''), remdstsite=nullif(EXCLUDED.remdstsite, ''), dsttype=nullif(EXCLUDED.dsttype, ''),
									mediatype=nullif(EXCLUDED.mediatype, ''), dstsite2=nullif(EXCLUDED.dstsite2, ''), dsttype2=nullif(EXCLUDED.dsttype2, ''),
									vendorpn=nullif(EXCLUDED.vendorpn, ''), moduleclass=nullif(EXCLUDED.moduleclass, ''), altname=nullif(EXCLUDED.altname, ''),
									sys_pollstatus=EXCLUDED.sys_pollstatus, lastseen=EXCLUDED.lastseen`, strings.Join(intfs, ","))
		_, err := tx.Exec(sql)
		if err != nil {
			return sql, err
		}

		// Delete obsolete Interface
		sql = fmt.Sprintf("delete from intf where device_id='%v' and lastseen<'%v'", deviceInst.DeviceId, ptime_str)
		_, err = tx.Exec(sql)
		if err != nil {
			return sql, err
		}
	}

	// ponport
	if len(ponports) > 0 {
		sql := fmt.Sprintf(`insert into ponport(
								id, device_name, device_id, device_ip,
								ifindex, name, ifname, ifdescr,
								ifalias, ifphyaddr, ifspeed, iftype,
								ifadmin, ifoper, ifconn,
								vendorpn, moduleclass,
								ponport, l1sp, l1_dl_max_bw, l1_ul_max_bw,
								dl_bw_remaining, ul_bw_remaining,
								sys_pollstatus, first, lastseen)
							values %v
							on conflict (id) do update
							set device_name=EXCLUDED.device_name, device_id=EXCLUDED.device_id, device_ip=EXCLUDED.device_ip,
									ifindex=EXCLUDED.ifindex, name=EXCLUDED.name, ifname=EXCLUDED.ifname, ifdescr=EXCLUDED.ifdescr,
									ifalias=EXCLUDED.ifalias, ifphyaddr=EXCLUDED.ifphyaddr, ifspeed=EXCLUDED.ifspeed, iftype=EXCLUDED.iftype,
									ifadmin=EXCLUDED.ifadmin, ifoper=EXCLUDED.ifoper, ifconn=EXCLUDED.ifconn,
									vendorpn=nullif(EXCLUDED.vendorpn, ''), moduleclass=nullif(EXCLUDED.moduleclass, ''),
									ponport=nullif(EXCLUDED.ponport, ''), l1sp=nullif(EXCLUDED.l1sp, ''), l1_dl_max_bw=EXCLUDED.l1_dl_max_bw, l1_ul_max_bw=EXCLUDED.l1_ul_max_bw,
									dl_bw_remaining=nullif(EXCLUDED.dl_bw_remaining, ''), ul_bw_remaining=nullif(EXCLUDED.ul_bw_remaining, ''),
									sys_pollstatus=EXCLUDED.sys_pollstatus, lastseen=EXCLUDED.lastseen`, strings.Join(ponports, ","))
		_, err := tx.Exec(sql)
		if err != nil {
			return sql, err
		}
	}

	// Delete obsolete Interface
	sql := fmt.Sprintf("delete from ponport where device_id='%v' and lastseen<'%v'", deviceInst.DeviceId, ptime_str)
	_, err := tx.Exec(sql)
	if err != nil {
		return sql, err
	}
	return "", nil
}

func saveBoards(tx *sql.Tx, deviceInst *Device, ptime_str string) (string, error) {
	boards := make([]string, 0)
	for _, board := range deviceInst.Boards {
		id := fmt.Sprintf("%d.%s", deviceInst.DeviceId, board.Id)
		boards = append(boards, fmt.Sprintf(`(
					'%v', %d, '%v', '%v',
					nullif('%v', ''), nullif('%v', ''), nullif('%v', ''), nullif('%v', ''),
					'%v', '%v')`,
			id, deviceInst.DeviceId, deviceInst.SysName, deviceInst.DeviceIp,
			board.BoardName, board.BoardType, board.BoardRole, board.OperStatus,
			ptime_str, ptime_str))
	}

	// Boards
	if len(boards) > 0 {
		sql := fmt.Sprintf(`insert into board(
								id, device_id, device_name, device_ip, boardname, boardtype, boardrole, operstatus, first, lastseen)
							values %v
								on conflict (id) do update
								set device_id=EXCLUDED.device_id,
								device_name=EXCLUDED.device_name,
								device_ip=EXCLUDED.device_ip,
								boardname=nullif(EXCLUDED.boardname, ''),
								boardtype=nullif(EXCLUDED.boardtype, ''),
								boardrole=nullif(EXCLUDED.boardrole, ''),
								operstatus=nullif(EXCLUDED.operstatus, ''),
								lastseen=EXCLUDED.lastseen`, strings.Join(boards, ","))
		_, err := tx.Exec(sql)
		if err != nil {
			return sql, err
		}
	}

	// Delete obsolete Boards
	log.Printf("delete from board where device_id='%v' and lastseen<'%v'", deviceInst.DeviceId, ptime_str)
	sql := fmt.Sprintf("delete from board where device_id='%v' and lastseen<'%v'", deviceInst.DeviceId, ptime_str)
	_, err := tx.Exec(sql)
	if err != nil {
		return sql, err
	}
	return "", nil
}

func RemoveInvalidCharacter(value string) string {
	// remove non-printable character
	strValue := strings.Map(func(r rune) rune {
		if unicode.IsPrint(r) {
			return r
		}
		return -1
	}, value)
	return strings.TrimSpace(strings.ReplaceAll(strings.ReplaceAll(strValue, "'", "''"), "\"", ""))
}

func GetIfSpeed(ifHighSpeed *SnmpVar, ifSpeed *SnmpVar, deviceInst Device) uint64 {
	if deviceInst.Network == "FTTx" {
		if deviceInst.Vendor == "GCOM" {
			// GCOM OLT: ifHighSpeed is not applicable
			// Use ifSpeed. However, ifSpeed has max value limitation.
			// If it return max value, assuem it's 10Gbps
			if ifSpeed != nil {
				// ifSpeed (bit-per-sec)
				val := ifSpeed.Value.(uint64)
				if val == 4294967295 {
					// value is exceed max value of 32 bit counter, return 10Gbps
					return 10000000000
				}
				return val
			}
		}
		if deviceInst.Vendor == "ZTE" {
			// ZTE OLT Model C620: ifHighSpeed return 0 for some interface (both intf & ponport)
			// If ifHighSpeed = 0 --> return ifSpeed
			// Otherwise, return ifHighSpeed
			if ifHighSpeed != nil && ifHighSpeed.Value != nil {
				if ifHighSpeed.Value.(uint64) == 0 {
					if ifSpeed != nil && ifSpeed.Value != nil {
						return ifSpeed.Value.(uint64)
					}
				}
			}
		}
	}
	// ifHighSpeed (1,000,000 bit-per-sec)
	if ifHighSpeed != nil && ifHighSpeed.Value != nil {
		return ifHighSpeed.Value.(uint64) * 1000000
	}
	// ifSpeed (bit-per-sec)
	if ifSpeed != nil && ifSpeed.Value != nil {
		return ifSpeed.Value.(uint64)
	}
	return 0
}

func GetLldpChassisId(snmpResult *SnmpResult) string {
	// Some OLT device such as GCOM (FTTx) return first 3 bytes "9c:65:ee" of mac-address which cause many duplicated chassisId
	lldpChassisId := snmpResult.getSnmpValue("lldpLocChassisId")
	if len(lldpChassisId) > 8 {
		log.Printf("lldpChassisId=[%s] {ok}", lldpChassisId)
		return lldpChassisId
	}

	// OLT Raisecom
	lldpChassisId = snmpResult.getSnmpValue("raisecomLocChassisId")
	if len(lldpChassisId) > 8 {
		log.Printf("lldpChassisId=[%s] {ok/raisecom}", lldpChassisId)
		return lldpChassisId
	}

	log.Printf("lldpChassisId=[%s] {blank}", lldpChassisId)
	return ""
}

func GetSwVersion(snmpResult *SnmpResult) string {
	hwSysVersion := snmpResult.getSnmpValue("hwSysVersion")
	if hwSysVersion != "" {
		return hwSysVersion
	}
	fbhSwVersion := snmpResult.getSnmpValue("fbhSwVersion")
	if fbhSwVersion != "" {
		return fbhSwVersion
	}
	return ""
}

func GetDeviceModel(snmpResult *SnmpResult) string {
	fbhFrameName := snmpResult.getSnmpValue("fbhFrameName")
	if fbhFrameName != "" {
		return fbhFrameName
	}
	return ""
}

type Device struct {
	DeviceId         int64
	DeviceIp         string
	ChassisId        string
	SysName          string
	SysDescr         string
	SysObjectID      string // Huawei OLT for extract device model
	Network          string
	Topology         string
	Community        string
	Engine           string // discovery.engine
	Agent            string // discovery.agent
	DiscoveryId      string // discovery.id
	DiscoveryPollInt int    // discovery.pollInt
	Descr            string // formatted sysDescr
	Vendor           string
	Model            string
	SwVersion        string
	Sitename         string
	Province         string
	PollStatus       int64
	Latitude         float64 // CR2026 - FTTx
	Longitude        float64 // CR2026 - FTTx
	OltType          string  // CR2026 - FTTx
	Interfaces       []*Interface
	Boards           []*Board               // CR2026 - FTTx
	Data             map[string]interface{} // CR2026 - nokia-altiplano discovery
}

type Interface struct {
	IfIndex    string
	IfName     string
	IfSpeed    uint64
	IfAdmin    string
	IfOper     string
	IfDescr    string
	IfAlias    string
	IfTopology string
	IfDstIp    string
	IfType     string
	IfPhyAddr  string
	IfConn     int64
	Name       string
	DstName    string
	DstPort    string
	DstSite    string
	DstType    string
	RemDstSite string
	MediaType  string
	PollStatus int64
	PonPort    string
	Save       bool
	DstSite2   string // hostname of DstSite
	DstType2   string // device.topology of DstSite2

	// Service API
	L1_SPLT         string
	L1_DL_MAX_BW    string
	L1_UL_MAX_BW    string
	DL_BW_REMAINING string
	UL_BW_REMAINING string

	// FTTx Optical Module
	VendorPn    string
	ModuleClass string

	// CR2026
	AltName      string // intf.altname
	NokiaDstSite string // intf.dstsite
}

type Board struct {
	Id         string
	BoardName  string
	BoardType  string
	BoardRole  string
	OperStatus string
}

type ByIfSpeedAndIfName []*Interface

func (a ByIfSpeedAndIfName) Len() int {
	return len(a)
}

func (v ByIfSpeedAndIfName) Less(i, j int) bool {
	if v[i].IfSpeed == v[j].IfSpeed {
		// If speeds are equal, compare by name asc
		return v[i].IfName < v[j].IfName
	}
	// compare IfSpeed desc
	return v[i].IfSpeed > v[j].IfSpeed
}

func (a ByIfSpeedAndIfName) Swap(i, j int) {
	a[i], a[j] = a[j], a[i]
}
