package snmplib

import (
	"database/sql"
	"log"
	"regexp"
	"time"
)

type LookupService struct {
	task           *DiscoveryConfig
	Ip2Topology    map[string]string
	ProvinceCode   map[string]string
	DeviceLookup   map[string]Device
	DiscDeviceInfo map[string]DiscDeviceInfo // disc_device_info
	db             *sql.DB
}

func NewLookupService(task *DiscoveryConfig) (*LookupService, error) {

	db, err := sql.Open("postgres", task.Setting.DbConnection)
	if err != nil {
		log.Panic(err)
	}
	// defer db.Close()

	// create mapping from disc.ip --> topology
	ip2Topology, err := loadIp2Topology(db)
	if err != nil {
		return nil, err
	}

	provinceCode, err := loadProvinceCode(db)
	if err != nil {
		return nil, err
	}

	deviceLookup, err := loadDeviceLookup(db)
	if err != nil {
		return nil, err
	}

	discDeviceInfo, err := loadDiscDeviceInfo(db)
	if err != nil {
		return nil, err
	}

	lookupService := LookupService{
		task:           task,
		Ip2Topology:    *ip2Topology,
		ProvinceCode:   *provinceCode,
		DeviceLookup:   *deviceLookup,
		DiscDeviceInfo: *discDeviceInfo,
		db:             db,
	}
	return &lookupService, nil
}

func loadIp2Topology(db *sql.DB) (*map[string]string, error) {
	ip2Topology := make(map[string]string, 1000)
	rows, err := db.Query(`select ip_range, topology from disc where enabled = true order by 1`)
	if err != nil {
		log.Printf("Error! %v", err)
		return &ip2Topology, nil
	}
	defer rows.Close()

	for rows.Next() {
		var ip_range string
		var topology string
		rows.Scan(&ip_range, &topology)
		for _, ipaddr := range convert2IpList(ip_range) {
			ip2Topology[ipaddr] = topology
		}
	}
	log.Printf("loadIp2Topology return %d entries", len(ip2Topology))
	return &ip2Topology, nil
}

func loadProvinceCode(db *sql.DB) (*map[string]string, error) {

	provinceCode := make(map[string]string, 2000)
	rows, err := db.Query(`select code, province_th||' / '||district_th from province_code order by 1`)
	if err != nil {
		log.Printf("Error! %v", err)
		return &provinceCode, err
	}
	defer rows.Close()

	for rows.Next() {
		var key string
		var value string
		rows.Scan(&key, &value)
		provinceCode[key] = value
	}
	log.Printf("LoadProvinceCode return %d entries", len(provinceCode))
	return &provinceCode, nil
}

func loadDeviceLookup(db *sql.DB) (*map[string]Device, error) {
	// key = chassisid and name
	deviceLookup := make(map[string]Device, 10000)
	rows, err := db.Query(`SELECT id,
														chassisid,
														name,
														network, 
														COALESCE(vendor, '') AS vendor
													FROM (
													SELECT id,
																chassisid,
																name,
																network,
																vendor,
																lastseen,
																ROW_NUMBER() OVER (PARTITION BY chassisid ORDER BY lastseen DESC) AS rn
													FROM device
													WHERE chassisid IS NOT NULL AND chassisid != ''
													) AS RankedDevices
													WHERE rn = 1`)
	if err != nil {
		log.Printf("Error! %v", err)
		return &deviceLookup, err
	}
	defer rows.Close()

	cnt := 0
	for rows.Next() {
		var deviceId int64
		var chassisid string
		var name string
		var network string
		var vendor string
		rows.Scan(&deviceId, &chassisid, &name, &network, &vendor)
		deviceLookup[chassisid] = Device{DeviceId: deviceId, ChassisId: chassisid, SysName: name, Network: network, Vendor: vendor}
		deviceLookup[name] = Device{DeviceId: deviceId, ChassisId: chassisid, SysName: name, Network: network, Vendor: vendor}
		cnt += 1
	}
	log.Printf("LoadDeviceLookup return %d entries", cnt)
	return &deviceLookup, nil
}

func loadDiscDeviceInfo(db *sql.DB) (*map[string]DiscDeviceInfo, error) {

	discDeviceInfo := make(map[string]DiscDeviceInfo, 1000)
	rows, err := db.Query(`select name, ip, model, swversion from disc_device_info`)
	if err != nil {
		log.Printf("Error! %v", err)
		return &discDeviceInfo, err
	}
	defer rows.Close()

	for rows.Next() {
		var entity DiscDeviceInfo
		rows.Scan(&entity.Name, &entity.Ip, &entity.Model, &entity.SwVersion)
		discDeviceInfo[entity.Name] = entity
	}
	log.Printf("loadDiscDeviceInfo return %d entries", len(discDeviceInfo))
	return &discDeviceInfo, nil
}

func (service *LookupService) loadDiscQrunL1(device string) (DiscQrunL1, error) {

	discQrunL1 := DiscQrunL1{
		ponports: make(map[string]DiscQrunL1PonPort),
	}
	rows1, err := service.db.Query(`SELECT device, latitude, longitude FROM disc_qrun_device WHERE device=$1`, device)
	if err != nil {
		log.Printf("Error! %v", err)
		return discQrunL1, err
	}
	defer rows1.Close()

	if rows1.Next() {
		rows1.Scan(&discQrunL1.device, &discQrunL1.latitude, &discQrunL1.longitude)
	}

	rows2, err := service.db.Query(`SELECT device, ponport, l1name, l1_dl_max_bw, l1_ul_max_bw, dl_bw_remaining, ul_bw_remaining, latitude, longitude
																 FROM disc_qrun_l1
																 WHERE device=$1`, device)
	if err != nil {
		log.Printf("Error! %v", err)
		return discQrunL1, err
	}
	defer rows2.Close()

	for rows2.Next() {
		var entity DiscQrunL1PonPort
		rows2.Scan(&entity.device, &entity.ponport, &entity.l1name, &entity.l1_dl_max_bw, &entity.l1_ul_max_bw, &entity.dl_bw_remaining, &entity.ul_bw_remaining, &discQrunL1.latitude, &discQrunL1.longitude)
		discQrunL1.ponports[entity.ponport] = entity
	}
	log.Printf("loadDiscQrunL1 %s return %d entries", device, len(discQrunL1.ponports))
	return discQrunL1, nil
}

func (service *LookupService) saveDiscQrunL1(device string, discQrunL1 DiscQrunL1) error {

	tx, err := service.db.Begin()
	if err != nil {
		return err
	}

	// delete existing records
	_, err = tx.Exec(`DELETE FROM disc_qrun_device WHERE device=$1`, device)
	if err != nil {
		return err
	}
	_, err = tx.Exec(`DELETE FROM disc_qrun_l1 WHERE device=$1`, device)
	if err != nil {
		return err
	}

	now := time.Now()
	log.Printf("saveDiscQrunL1: %v|%v|%v", device, discQrunL1.latitude, discQrunL1.longitude)
	_, err = tx.Exec(`INSERT INTO disc_qrun_device(device, latitude, longitude, lastupdate)
											VALUES($1,$2,$3,$4)
											ON CONFLICT (device) DO NOTHING`,
		device, discQrunL1.latitude, discQrunL1.longitude, now)
	if err != nil {
		return err
	}

	for _, entry := range discQrunL1.ponports {
		log.Printf("saveDiscQrunL1: %v|%v|%v", device, entry.ponport, entry.l1name)
		_, err = tx.Exec(`INSERT INTO disc_qrun_l1(device, ponport, l1name, l1_dl_max_bw, l1_ul_max_bw, dl_bw_remaining, ul_bw_remaining, latitude, longitude, lastupdate)
											VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
											ON CONFLICT (device, ponport) DO NOTHING`,
			entry.device, entry.ponport, entry.l1name, entry.l1_dl_max_bw, entry.l1_ul_max_bw, entry.dl_bw_remaining, entry.dl_bw_remaining, entry.latitude, entry.longitude, now)
		if err != nil {
			return err
		}
	}

	// commit
	err = tx.Commit()
	if err != nil {
		return err
	}
	return nil
}

func (service *LookupService) mapDiscDeviceInfo(deviceInst *Device) {
	entry, ok := service.DiscDeviceInfo[deviceInst.SysName]
	if ok {
		deviceInst.Model = entry.Model
		deviceInst.SwVersion = entry.SwVersion
		log.Printf("mapDiscDeviceInfo: disc_device_info: %s|%s|%s", deviceInst.SysName, deviceInst.Model, deviceInst.SwVersion)
	}
}

func (service *LookupService) lookupTopologyByIpAddr(ifalias string) (string, string) {
	// extract ip addr from ifalias and lookup from ip2Topology
	re := regexp.MustCompile(`.*[-_](?P<ipaddr>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})([^\d])?.*`)
	m := re.FindAllStringSubmatch(ifalias, -1)
	if m != nil {
		ipaddr := m[0][1]
		iftopology, ok := (service.Ip2Topology)[ipaddr]
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

type DiscDeviceInfo struct {
	Name      string
	Ip        string
	Model     string
	SwVersion string
}
