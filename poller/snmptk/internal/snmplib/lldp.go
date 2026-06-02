package snmplib

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	_ "github.com/lib/pq"
)

var (
	Fiberhome_Regex       = regexp.MustCompile(`.*FP.*[ ](\d+)\/(\d+)$`)
	Raisecom_UplinkIfName = regexp.MustCompile(`.*gigabitethernet(\d+)\/(\d+)$`)
	GCOM_UplinkIfName     = regexp.MustCompile(`e(\d+)\/(\d+)$`)
)

type LldpMapper struct {
	task          *DiscoveryConfig
	lookupService *LookupService
}

type LldpEntry struct {
	Index        string // lldpLocPortTable.lldpLocPortNum, lldpRemTable.lldpRemLocalPortNum
	LocPortId    string // lldpLocPortTable.lldpLocPortId
	RemPortId    string // lldpRemTable.lldpRemPortId
	RemChassisId string // lldpRemTable.lldpRemChassisId
	RemSysName   string // lldpRemTable.lldpRemSysName
}

func NewLldpMapper(task *DiscoveryConfig, lookupService *LookupService) *LldpMapper {
	lldpMapper := LldpMapper{task: task, lookupService: lookupService}
	return &lldpMapper
}

func (mapper *LldpMapper) mapLldp(deviceInst *Device, snmpResult *SnmpResult) {

	lldpTableByIfName := mapper.getLldpTable(deviceInst, snmpResult)
	if debug {
		s, _ := json.MarshalIndent(lldpTableByIfName, "", " ")
		log.Printf("lldpTableByIfName = %s", string(s))
	}

	for _, intf := range deviceInst.Interfaces {
		// set default value to blank
		intf.DstName = ""
		intf.DstPort = ""
		lldpEntry, ok := lldpTableByIfName[intf.IfName]
		if ok {
			// default method, lookup by ifName
			intf.DstName = RemoveInvalidCharacter(lldpEntry.RemSysName)
			intf.DstPort = RemoveInvalidCharacter(lldpEntry.RemPortId)

		} else {
			if deviceInst.Network == "FTTx" {
				if deviceInst.Vendor == "Dasan" {
					// OLT Dasan
					// if lookup by ifIname failed, try ifIndex
					lldpEntry, ok = lldpTableByIfName[intf.IfIndex]
					if ok {
						intf.DstName = RemoveInvalidCharacter(lldpEntry.RemSysName)
						intf.DstPort = RemoveInvalidCharacter(lldpEntry.RemPortId)
					}

				} else if deviceInst.Vendor == "Fiberhome" {
					// OLT Fiberhome
					// row.Index = (slot x 33554432) + (port x 524288)
					m := Fiberhome_Regex.FindAllStringSubmatch(intf.IfName, -1)
					if m != nil {
						slot := m[0][1]
						port := m[0][2]
						if slot_no, err := strconv.Atoi(slot); err == nil {
							if port_no, err := strconv.Atoi(port); err == nil {
								idx := fmt.Sprintf("%d", ((slot_no * 33554432) + (port_no * 524288)))
								lldpEntry, ok := lldpTableByIfName[idx]
								if ok {
									intf.DstName = RemoveInvalidCharacter(lldpEntry.RemSysName)
									intf.DstPort = RemoveInvalidCharacter(lldpEntry.RemPortId)
								}
								if debug {
									log.Printf("mapLldp: %s, slot=%d, port=%d, idx=%s, ok=%v", intf.IfName, slot_no, port_no, idx, ok)
								}
							}
						}
					}
				}
			}
		}
	}
}

func (mapper *LldpMapper) getLldpTable(deviceInst *Device, snmpResult *SnmpResult) map[string]*LldpEntry {
	if deviceInst.Network == "FTTx" {
		if deviceInst.Vendor == "Dasan" {
			lldpRemTable_FTTx_Dasan, ok := snmpResult.SnmpTables["lldpRemTable_FTTx_Dasan"]
			if ok {
				// key = ifIndex
				return mapper.get_lldpRemTable_FTTx_Dasan(deviceInst, lldpRemTable_FTTx_Dasan)
			}

		} else if deviceInst.Vendor == "Fiberhome" {
			lldpRemTable_FTTx_Fiberhome, ok := snmpResult.SnmpTables["lldpRemTable_FTTx_Fiberhome"]
			if ok {
				// key = computed index from slot/port
				return mapper.get_lldpRemTable_FTTx_Fiberhome(deviceInst, lldpRemTable_FTTx_Fiberhome)
			}

		} else if deviceInst.Vendor == "Raisecom" {
			lldpLocTable_FTTx_Raisecom, ok1 := snmpResult.SnmpTables["lldpLocTable_FTTx_Raisecom"]
			lldpRemTable_FTTx_Raisecom, ok2 := snmpResult.SnmpTables["lldpRemTable_FTTx_Raisecom"]
			if ok1 && ok2 {
				return mapper.get_lldp_FTTx_Raisecom(deviceInst, lldpLocTable_FTTx_Raisecom, lldpRemTable_FTTx_Raisecom)
			}
		} else if deviceInst.Vendor == "GCOM" {
			lldpRemTable, ok := snmpResult.SnmpTables["lldpRemTable_FTTx_GCOM"]
			if ok {
				return mapper.get_lldp_FTTx_GCOM(deviceInst, lldpRemTable)
			}
		}
	}
	// key = ifName
	return mapper.getLldpTable_standard(deviceInst, snmpResult)
}

func (mapper *LldpMapper) get_lldpRemTable_FTTx_Fiberhome(deviceInst *Device, lldpRemTable *SnmpTable) map[string]*LldpEntry {

	lldpTableByIfName := make(map[string]*LldpEntry) // key = ifIndex (local device)
	if debug {
		log.Printf("lldpRemTable_FTTx_Fiberhome = %s", lldpRemTable.ToJson())
	}

	for _, row := range lldpRemTable.Entries {
		// row.Index = "<lldpRowId>"
		// lldpLocPortId = "3.1" format: <slot>.<port>
		// row.Index = (slot x 33554432) + (port x 524288)
		lldpLocPortId := row.GetValue("lldpLocPortId")
		lldpRemPortId := row.GetValue("lldpRemPortId")
		lldpRemSysName := row.GetValue("lldpRemSysName")

		lldpTableByIfName[row.Index] = &LldpEntry{
			Index:        row.Index,
			LocPortId:    lldpLocPortId,
			RemChassisId: "",
			RemPortId:    lldpRemPortId,
			RemSysName:   lldpRemSysName,
		}
	}
	return lldpTableByIfName
}

func (mapper *LldpMapper) get_lldpRemTable_FTTx_Dasan(deviceInst *Device, lldpRemTable *SnmpTable) map[string]*LldpEntry {

	lldpTableByIfName := make(map[string]*LldpEntry) // key = ifIndex (local device)
	if debug {
		log.Printf("lldpRemTable_FTTx_Dasan = %s", lldpRemTable.ToJson())
	}

	for _, row := range lldpRemTable.Entries {
		// row.Index = "<ifindex>.1"
		tokens := strings.Split(row.Index, ".")
		if len(tokens) == 2 {
			ifindex := tokens[0]
			sleLldpRemPortId := row.GetValue("sleLldpRemPortId")
			sleLldpRemSysName := row.GetValue("sleLldpRemSysName")

			lldpTableByIfName[ifindex] = &LldpEntry{
				Index:        ifindex,
				LocPortId:    "",
				RemChassisId: "",
				RemPortId:    sleLldpRemPortId,
				RemSysName:   sleLldpRemSysName,
			}
		}
	}
	return lldpTableByIfName
}

func (mapper *LldpMapper) get_lldp_FTTx_Raisecom(deviceInst *Device, lldpLocTable *SnmpTable, lldpRemTable *SnmpTable) map[string]*LldpEntry {
	if debug {
		log.Printf("lldpLocTable = %s", lldpLocTable.ToJson())
		log.Printf("lldpRemTable = %s", lldpRemTable.ToJson())
	}

	// OLT Raisecom
	// lldpRemTable: return logical port such as 'port-channel1'. We can't map to physical port.
	// lldpLocTable: return physical port on remote device
	// Therfore, use special rule to map lldpLocTable remote port to local port
	//	1.) use local port with 10Gbps and ifOperSutats = 'up', order by name, ifName pattern "gigabitethernetx/y" where x=1, y=1-4
	//	2.) use local port with 1Gbps and status = 'up', order by name, ifName pattern "ten-gigabitethernetx/y" where x=1, y=5-6
	// 		gigabitethernet1/1
	// 		gigabitethernet1/2
	// 		gigabitethernet1/3
	// 		gigabitethernet1/4
	// 		ten-gigabitethernet1/5
	// 		ten-gigabitethernet1/6

	activeIntfs, _ := deviceInst.getActiveIntfsOrderByIfSpeedAndIfName()

	lldpTableByIfName := make(map[string]*LldpEntry) // key = ifName (local intf)
	idx := 0
	for _, row := range lldpRemTable.Entries {
		if idx <= len(activeIntfs)-1 {
			lldpRemSysName := RemoveInvalidCharacter(row.GetValue("lldpRemSysName"))
			lldpRemPortId := RemoveInvalidCharacter(row.GetValue("lldpRemPortId"))

			locIntf := activeIntfs[idx]
			lldpTableByIfName[locIntf.IfName] = &LldpEntry{Index: locIntf.IfName, LocPortId: locIntf.IfIndex, RemChassisId: "", RemSysName: lldpRemSysName, RemPortId: lldpRemPortId}
			idx++
		}
	}
	return lldpTableByIfName
}

func (mapper *LldpMapper) get_lldp_FTTx_GCOM(deviceInst *Device, lldpRemTable *SnmpTable) map[string]*LldpEntry {
	if debug {
		log.Printf("lldpRemTable = %s", lldpRemTable.ToJson())
	}

	// OLT GCOM
	// lldpRemTable: return remote port without local port information
	// Therfore, use special rule to map lldpLocTable remote port to local port
	//	1.) use local port with 10Gbps and ifOperSutats = 'up', order by name, ifName pattern "ex/y" where x,y is numeric value
	//	2.) use local port with 1Gbps and status = 'up', order by name, ifName pattern "ex/y" where x,y is numeric value
	// 		e2/1
	//		e2/2

	activeIntfs, _ := deviceInst.getActiveIntfsOrderByIfSpeedAndIfName()

	lldpTableByIfName := make(map[string]*LldpEntry) // key = ifName (local intf)
	idx := 0
	for _, row := range lldpRemTable.Entries {
		if idx <= len(activeIntfs)-1 {
			lldpRemSysName := RemoveInvalidCharacter(row.GetValue("lldpRemSysName"))
			lldpRemPortId := RemoveInvalidCharacter(row.GetValue("lldpRemPortId"))

			locIntf := activeIntfs[idx]
			lldpTableByIfName[locIntf.IfName] = &LldpEntry{Index: locIntf.IfName, LocPortId: locIntf.IfIndex, RemChassisId: "", RemSysName: lldpRemSysName, RemPortId: lldpRemPortId}
			idx++
		}
	}
	return lldpTableByIfName

	/*
		lldpTableByIfName := make(map[string]*LldpEntry) // key = ifIndex (local intf)
		if lldpRemTable.Error == "" {
			for _, row := range lldpRemTable.Entries {
				// .1.0.8802.1.1.2.1.4.1.1.7.4094298703.13.1 = STRING: "xgei-1/7/0/4"
				// row.Index = "<x>.<ifindex>.<z>"
				tokens := strings.Split(row.Index, ".")
				if len(tokens) == 3 {
					ifindex := strings.Split(row.Index, ".")[1]
					lldpRemPortId := row.GetValue("lldpRemPortId")
					lldpRemSysName := row.GetValue("lldpRemSysName")

					if lldpRemPortId != "" && lldpRemSysName != "" {
						lldpTableByIfName[ifindex] = &LldpEntry{
							Index:        ifindex,
							LocPortId:    "",
							RemChassisId: "",
							RemPortId:    lldpRemPortId,
							RemSysName:   lldpRemSysName,
						}
					}
				}
			}
		}
		return lldpTableByIfName
	*/
}

func (mapper *LldpMapper) getLldpTable_standard(deviceInst *Device, snmpResult *SnmpResult) map[string]*LldpEntry {
	if debug {
		lldpLocPortTable := snmpResult.SnmpTables["lldpLocPortTable"]
		lldpRemTable := snmpResult.SnmpTables["lldpRemTable"]

		log.Printf("lldpLocPortTable = %s", lldpLocPortTable.ToJson())
		log.Printf("lldpRemTable = %s", lldpRemTable.ToJson())
	}

	// LLDP
	lldpTableByIdx := make(map[string]*LldpEntry)    // key = lldpTableIndex
	lldpTableByIfName := make(map[string]*LldpEntry) // key = lldpLocPortName (ifName)

	// lldpLocPortTable
	lldpLocPortTable, ok := snmpResult.SnmpTables["lldpLocPortTable"]
	if ok && lldpLocPortTable.Error == "" {
		for _, row := range lldpLocPortTable.Entries {
			lldpLocPortId := row.GetValue("lldpLocPortId")
			if lldpLocPortId != "" {
				lldpTableByIdx[row.Index] = &LldpEntry{Index: row.Index, LocPortId: lldpLocPortId}
				// log.Printf("lldpTableByIdx: %s|%s", row.Index, lldpLocPortId)
			}
		}
	}

	// lldpRemTable
	lldpRemTable, ok := snmpResult.SnmpTables["lldpRemTable"]
	if ok && lldpRemTable.Error == "" {
		for _, row := range lldpRemTable.Entries {
			lldpRemChassisId := RemoveInvalidCharacter(row.GetValue("lldpRemChassisId"))
			lldpRemSysName := RemoveInvalidCharacter(row.GetValue("lldpRemSysName"))
			lldpRemPortId := RemoveInvalidCharacter(row.GetValue("lldpRemPortId"))

			if lldpRemChassisId != "" && lldpRemPortId != "" && lldpRemSysName != "" {

				// Special case for CPE connected to OLT Raisecom
				// if lldpRemPortId = 'port-channel1' --> discard
				device, ok := mapper.lookupService.DeviceLookup[lldpRemChassisId]
				if ok {
					if device.Network == "FTTx" && device.Vendor == "Raisecom" && lldpRemPortId == "port-channel1" {
						log.Printf("lldpRemTable: %s|%s|%s|%s|LldpDiscard", lldpRemChassisId, lldpRemSysName, lldpRemPortId, device.Vendor)
						continue
					}
				}

				lldpIndex := strings.Split(row.Index, ".")[1]
				lldpEntry, ok := lldpTableByIdx[lldpIndex]
				if ok {
					lldpEntry.RemChassisId = lldpRemChassisId
					lldpEntry.RemSysName = lldpRemSysName
					lldpEntry.RemPortId = lldpRemPortId
					lldpTableByIfName[lldpEntry.LocPortId] = lldpEntry
					// log.Printf("lldpTableByIfName: %s|%v", lldpEntry.LocPortId, lldpEntry)
				}
			}
		}
	}
	return lldpTableByIfName
}

func (deviceInst *Device) getActiveIntfsOrderByIfSpeedAndIfName() ([]*Interface, error) {
	activeIntfs := make([]*Interface, 0)
	var ifname_re *regexp.Regexp
	if deviceInst.Vendor == "GCOM" {
		ifname_re = GCOM_UplinkIfName
	} else if deviceInst.Vendor == "Raisecom" {
		ifname_re = Raisecom_UplinkIfName
	} else {
		return activeIntfs, errors.New("uplink vendor not supported")
	}

	for _, intf := range deviceInst.Interfaces {
		m := ifname_re.FindAllStringSubmatch(intf.IfName, -1)
		if m != nil {
			if intf.IfOper == "up" && intf.IfSpeed >= 1000000000 {
				activeIntfs = append(activeIntfs, intf)
			}
		}
	}
	// sort by IfSpeed descending and IfName ascending
	sort.Sort(ByIfSpeedAndIfName(activeIntfs))
	if debug {
		log.Printf("activeIntfs = %v", activeIntfs)
	}
	return activeIntfs, nil
}

func (mapper *LldpMapper) update_lldp_uplink(db *sql.DB) error {
	start := time.Now()
	// beging transaction
	tx, err := db.Begin()
	if err != nil {
		return err
	}

	sql := `update intf set dstname=$1, dstport=$2, remdstsite='lldp' where device_id=$3 and ifname=$4`
	update_lldp, err := tx.Prepare(sql)
	if err != nil {
		return err
	}
	defer update_lldp.Close()

	sql = `WITH latest_device AS (SELECT id,
						name,
						lastseen,
						ROW_NUMBER() OVER (PARTITION BY name ORDER BY lastseen DESC) AS row_num
				 FROM device)
				 SELECT id FROM latest_device WHERE row_num = 1 AND name = $1`
	query_device_id_by_name, err := tx.Prepare(sql)
	if err != nil {
		return err
	}
	defer query_device_id_by_name.Close()

	sql = `WITH latest_device AS
					(SELECT id,
									name,
									vendor,
									lastseen,
									ROW_NUMBER() OVER (PARTITION BY name ORDER BY lastseen DESC) AS row_num
							FROM device
							WHERE network = 'FTTx' AND vendor in ('GCOM', 'Raisecom')
					),
					lldp_intf AS (
						select
								coalesce(intf.device_name, '') 	as device_name,
								coalesce(intf.ifname, '')				as ifname,
								coalesce(intf.dstname, '')			as dstname,
								coalesce(intf.dstport, '')			as dstport
						from device,
								intf
						where device.id = intf.device_id
							and intf.remdstsite = 'lldp'
							and device_id in (select id from latest_device)
					)
					select device_name, ifname, dstname, dstport from lldp_intf order by 1,2`

	// do not use same transaction as update statement, otherwise, it will return error
	rows, err := db.Query(sql)
	if err != nil {
		return err
	}
	defer rows.Close()

	cnt := 0
	for rows.Next() {
		var device_name string
		var ifname string
		var dstname string
		var dstport string
		err := rows.Scan(&device_name, &ifname, &dstname, &dstport)
		if err != nil {
			return err
		}

		// query device_id by dstname
		var device_id int64
		err = query_device_id_by_name.QueryRow(dstname).Scan(&device_id)
		if err != nil {
			// device_id not found
			// log.Printf("update_lldp_uplink: %d|%s|%s => %s|%s [err=dstname %s not found]", device_id, dstname, dstport, device_name, ifname, dstname)
			continue
		}

		// update lldp
		_, err = update_lldp.Exec(device_name, ifname, device_id, dstport)
		if err != nil {
			log.Printf("update_lldp_uplink: %d|%s|%s => %s|%s [err=%v]", device_id, dstname, dstport, device_name, ifname, err)
			continue
		}

		cnt++
		// rowsAffected, _ := ret.RowsAffected()
		// log.Printf("update_lldp_uplink: %d|%s|%s => %s|%s [ok, %d]", device_id, dstname, dstport, device_name, ifname, rowsAffected)
	}

	tx.Commit()
	log.Printf("update_lldp_uplink: updated %d records in %s", cnt, time.Since(start))
	return nil
}
