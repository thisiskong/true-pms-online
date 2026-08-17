package snmplib

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"time"
)

type IntfRev struct {
	ObjType  string // intf_rev or ponport_rev
	Id       string
	DeviceId int64
	IfIndex  string
	IfName   string
	IfOper   string
	IfSpeed  uint64
	First    time.Time
	Lastseen time.Time
	Rev      int32 // revision no
}

func saveIntfRev(tx *sql.Tx, deviceInst *Device, ptime time.Time) (string, error) {
	// process only network = 'FTTx'
	if deviceInst.Network != "FTTx" {
		return "", nil
	}

	// load intf_rev
	curIntfMap, last_sql_err, err := load_intf_rev(tx, deviceInst)
	if err != nil {
		return last_sql_err, err
	}

	// convert new intf_rev
	newIntfMap := map_intf_rev(deviceInst, ptime)
	toBeSaveIntfMap := generate_rev(ptime, curIntfMap, newIntfMap)

	// save changes to intf_rev
	err = save_intf_rev(tx, toBeSaveIntfMap)
	if err != nil {
		return "", err
	}

	// load ponport_rev
	curIntfMap, last_sql_err, err = load_ponport_rev(tx, deviceInst)
	if err != nil {
		return last_sql_err, err
	}

	// convert new ponport_rev
	newIntfMap = map_ponport_rev(deviceInst, ptime)
	toBeSaveIntfMap = generate_rev(ptime, curIntfMap, newIntfMap)

	// save changes to ponport_rev
	err = save_ponport_rev(tx, toBeSaveIntfMap)
	if err != nil {
		return "", err
	}
	return "", nil
}

func load_intf_rev(tx *sql.Tx, deviceInst *Device) (map[string]*IntfRev, string, error) {
	intfMap := map[string]*IntfRev{}
	sql := fmt.Sprintf(`select id, rev, device_id, ifindex, ifname, ifoper, ifspeed, first, lastseen
												from (
													select *, row_number() over (partition by id order by rev desc) as rownum
													from intf_rev where device_id = %d
												) x where rownum = 1`, deviceInst.DeviceId)
	rows, err := tx.Query(sql)
	if err != nil {
		return intfMap, sql, err
	}
	defer rows.Close()

	for rows.Next() {
		rev := IntfRev{ObjType: "intf_rev"}
		rows.Scan(&rev.Id, &rev.Rev, &rev.DeviceId, &rev.IfIndex, &rev.IfName, &rev.IfOper, &rev.IfSpeed, &rev.First, &rev.Lastseen)
		intfMap[rev.Id] = &rev
	}
	return intfMap, "", nil
}

func load_ponport_rev(tx *sql.Tx, deviceInst *Device) (map[string]*IntfRev, string, error) {
	intfMap := map[string]*IntfRev{}
	sql := fmt.Sprintf(`select id, rev, device_id, ifindex, ifname, ifoper, ifspeed, first, lastseen
												from (
													select *, row_number() over (partition by id order by rev desc) as rownum
													from ponport_rev where device_id = %d
												) x where rownum = 1`, deviceInst.DeviceId)
	rows, err := tx.Query(sql)
	if err != nil {
		return intfMap, sql, err
	}
	defer rows.Close()

	for rows.Next() {
		rev := IntfRev{ObjType: "ponport_rev"}
		rows.Scan(&rev.Id, &rev.Rev, &rev.DeviceId, &rev.IfIndex, &rev.IfName, &rev.IfOper, &rev.IfSpeed, &rev.First, &rev.Lastseen)
		intfMap[rev.Id] = &rev
	}
	return intfMap, "", nil
}

func map_intf_rev(deviceInst *Device, ptime time.Time) map[string]*IntfRev {
	intfMap := map[string]*IntfRev{}
	for _, intf := range deviceInst.Interfaces {
		if !intf.Save || intf.PonPort != "" {
			// discard
			continue
		}

		id := fmt.Sprintf("%d.%s", deviceInst.DeviceId, intf.IfIndex)
		rev := IntfRev{
			ObjType:  "intf_rev",
			Id:       id,
			DeviceId: deviceInst.DeviceId,
			IfIndex:  intf.IfIndex,
			IfName:   intf.IfName,
			IfOper:   intf.IfOper,
			IfSpeed:  intf.IfSpeed,
			First:    ptime,
			Lastseen: ptime,
			Rev:      1,
		}
		intfMap[id] = &rev
	}
	return intfMap
}

func map_ponport_rev(deviceInst *Device, ptime time.Time) map[string]*IntfRev {
	intfMap := map[string]*IntfRev{}
	for _, intf := range deviceInst.Interfaces {
		if !intf.Save || intf.PonPort == "" {
			// discard
			continue
		}

		id := fmt.Sprintf("%d.%s", deviceInst.DeviceId, intf.IfIndex)
		rev := IntfRev{
			ObjType:  "ponport_rev",
			Id:       id,
			DeviceId: deviceInst.DeviceId,
			IfIndex:  intf.IfIndex,
			IfName:   intf.IfName,
			IfOper:   intf.IfOper,
			IfSpeed:  intf.IfSpeed,
			First:    ptime,
			Lastseen: ptime,
			Rev:      1,
		}
		intfMap[id] = &rev
	}
	return intfMap
}

func compare(intf1 *IntfRev, intf2 *IntfRev, ptime time.Time) bool {
	// compare intf1 and intf2
	// compareIfOper: True if equals, otherwise, False
	return intf1.IfOper == intf2.IfOper
}

func generate_rev(ptime time.Time, curIntfMap map[string]*IntfRev, newIntfMap map[string]*IntfRev) map[string]*IntfRev {

	toBeSaveIntfMap := map[string]*IntfRev{}
	for id, curIntf := range curIntfMap {
		newIntf, ok := newIntfMap[id]
		if ok {
			// compare if any changes
			match := compare(newIntf, curIntf, ptime)
			if match {
				// NoChange: update lastseen of current revision
				rev := curIntf
				rev.Lastseen = ptime
				toBeSaveIntfMap[id] = rev
				// log.Printf("%s: {%s} ifoper=%s|%s, match=%v, rev=%d|%d, UpdateLastseen", newIntf.ObjType, id, curIntf.IfOper, newIntf.IfOper, match, curIntf.Rev, rev.Rev)

			} else {
				// Modify: create new revision
				rev := newIntf
				rev.Rev = curIntf.Rev + 1
				toBeSaveIntfMap[id] = rev
				// log.Printf("%s: {%s} ifoper=%s|%s, match=%v, rev=%d|%d, NewRev", id, newIntf.ObjType, curIntf.IfOper, newIntf.IfOper, match, curIntf.Rev, rev.Rev)
			}
		} else {
			// Delete: no action
		}
	}

	// copy new interfaces
	for id, intfNew := range newIntfMap {
		_, ok := curIntfMap[id]
		if !ok {
			// New: create new revision
			toBeSaveIntfMap[id] = intfNew
		}
	}
	return toBeSaveIntfMap
}

func save_intf_rev(tx *sql.Tx, intfRevs map[string]*IntfRev) error {
	if debug {
		s, _ := json.MarshalIndent(intfRevs, "", " ")
		log.Printf("save_intf_rev = %s", string(s))
	}

	for _, rev := range intfRevs {
		_, err := tx.Exec(`insert into intf_rev(id, rev, device_id, ifindex, ifname, ifoper, ifspeed, first, lastseen)
													values($1,$2,$3,$4,$5,$6,$7,$8,$9)
													on conflict(id, rev) do update set lastseen=$9`,
			rev.Id, rev.Rev, rev.DeviceId, rev.IfIndex, rev.IfName, rev.IfOper, rev.IfSpeed, rev.First, rev.Lastseen)
		if err != nil {
			return err
		}
	}
	return nil
}

func save_ponport_rev(tx *sql.Tx, intfRevs map[string]*IntfRev) error {
	if debug {
		s, _ := json.MarshalIndent(intfRevs, "", " ")
		log.Printf("save_ponport_rev = %s", string(s))
	}

	for _, rev := range intfRevs {
		_, err := tx.Exec(`insert into ponport_rev(id, rev, device_id, ifindex, ifname, ifoper, ifspeed, first, lastseen)
													values($1,$2,$3,$4,$5,$6,$7,$8,$9)
													on conflict(id, rev) do update set lastseen=$9`,
			rev.Id, rev.Rev, rev.DeviceId, rev.IfIndex, rev.IfName, rev.IfOper, rev.IfSpeed, rev.First, rev.Lastseen)
		if err != nil {
			return err
		}
	}
	return nil
}
