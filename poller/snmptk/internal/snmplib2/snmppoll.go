package snmplib2

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"time"

	"github.com/gosnmp/gosnmp"
	"go.uber.org/ratelimit"
	"gopkg.in/yaml.v2"
)

var UINT64_MAX = uint64(18446744073709551615)

var (
	logger gosnmp.Logger
)

func SnmpDebugEnable() {
	logger = gosnmp.NewLogger(log.New(os.Stdout, "", 0))
}

func loadSnmpPollConfig(filename string) *SnmpPollConfig {
	content, err := os.ReadFile(filename)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	var task SnmpPollConfig
	err = yaml.Unmarshal(content, &task)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	if task.SnmpPoll.ExpiredMultiplier == 0 {
		// expired multipler for isExpired() when compute delta, default value is 2.
		// This setting is useful for ONU PON polling as there're many missing data so we increase this multiplier to avoid expired data.
		task.SnmpPoll.ExpiredMultiplier = 2
	}
	return &task
}

func loadTarget(name string, config *SnmpPollConfig) ([]SnmpTarget, error) {
	jsonfile := fmt.Sprintf(".targets-%s.json", name)
	targets, err := loadTargetFromDb(config)
	if err == nil {
		// save to jsonfile
		saveTargetToJson(jsonfile, targets)
	} else {
		log.Printf("Error! %v", err)

		// try to use targets from saved file
		targets, err = loadTargetFromJson(jsonfile)
		if err != nil {
			log.Fatalf("Error! %v", err)
		}
	}
	return targets, nil
}

func loadTargetFromDb(config *SnmpPollConfig) ([]SnmpTarget, error) {
	// ZTE C300 very slow response: 10.239.123.2, 10.239.146.2
	// Test devices:
	// 	Vendor		Model		IP
	// 	--------------------------------------------
	// 	Huawei 		MA5600V8 	10.238.152.11
	//	ZTE 		C300 		10.239.131.2
	// 	ZTE 		C320 		10.239.152.26
	db, err := sql.Open("postgres", config.Setting.DbConnection)
	if err != nil {
		return nil, err
	}
	defer db.Close()

	cond, err := buildQuery(config.Setting, "ip")
	if err != nil {
		log.Fatalf("Error! %v", err)
	}

	sql := fmt.Sprintf(`select
				id, ip, community, coalesce(name, ''), coalesce(agent, ''),
				coalesce(network, ''), coalesce(topology, ''), coalesce(vendor, ''), coalesce(model, '')
			from (
				select id, ip, community, name, coalesce(usr_pollstatus, sys_pollstatus) pollstatus, pollint, agent,
					network, topology, vendor, model,
					row_number() over (partition by ip order by lastseen desc) as rownum
					from device
					where coalesce(usr_pollstatus, sys_pollstatus) = 1 and ( %s )
			) X
			where ( %s ) and rownum = 1 order by id`, config.SnmpPoll.SnmpTargetSqlQuery, cond)

	rows, err := db.Query(sql)
	if err != nil {
		return nil, err
	}

	device_cnt := 0
	ponport_cnt := 0
	odn_cnt := 0
	intf_cnt := 0
	targets := make([]SnmpTarget, 0)
	for rows.Next() {
		var id int64
		target := SnmpTarget{
			Port:               161,
			Version:            gosnmp.Version2c,
			Timeout:            config.SnmpPoll.SnmpOption.Timeout,
			Retries:            config.SnmpPoll.SnmpOption.Retries,
			MaxRepetition:      config.SnmpPoll.SnmpOption.MaxRepetition,
			MaxReqOid:          config.SnmpPoll.SnmpOption.MaxReqOid,
			ExpTime:            config.SnmpPoll.SnmpOption.ExpTime,
			IcmpCount:          config.SnmpPoll.IcmpCount,
			IcmpInterval:       config.SnmpPoll.IcmpInterval,
			IcmpTimeout:        config.SnmpPoll.IcmpTimeout,
			Flags:              make([]string, 0),
			InterfacesIfIndex:  make(map[string]*Intf),
			InterfacesIfName:   make(map[string]*Intf),
			PonPortsIfIndex:    make(map[string]*PonPort),
			PonPortsIfName:     make(map[string]*PonPort),
			PonPortsName:       make(map[string]*PonPort),
			PonPortsNokiaPonId: make(map[string]*PonPort),
		}
		err = rows.Scan(&id, &target.IP, &target.Community, &target.Device, &target.Agent, &target.Network, &target.Topology, &target.Vendor, &target.Model)
		if err != nil {
			return nil, err
		}

		// load intf
		rows2, err2 := db.Query(fmt.Sprintf(`select ifindex, ifname, ifspeed, coalesce(ifoper, '')
																					from intf
																					where
																					coalesce(usr_pollstatus, sys_pollstatus) = 1
																					and ifindex is not null and ifindex != ''
																					and device_id = %d`, id))
		if err2 != nil {
			panic(err2)
			// return nil, err2
		}
		for rows2.Next() {
			intf := Intf{}
			rows2.Scan(&intf.Ifindex, &intf.Ifname, &intf.Ifspeed, &intf.Ifoper)
			target.InterfacesIfIndex[intf.Ifindex] = &intf
			target.InterfacesIfName[intf.Ifname] = &intf
			intf_cnt += 1
		}

		// load ponport
		rows2, err2 = db.Query(`select ifindex, coalesce(ifname, ''), coalesce(ponport, ''), coalesce(l1sp, ''), coalesce(ifoper, ''), ifspeed
											from ponport
											where
												coalesce(usr_pollstatus, sys_pollstatus) = 1
												and ifindex is not null and ifindex != ''
												and device_id = $1`, id)
		if err2 != nil {
			return nil, err2
		}
		for rows2.Next() {
			ponport := PonPort{}
			rows2.Scan(&ponport.Ifindex, &ponport.Ifname, &ponport.PonPort, &ponport.L1sp, &ponport.Ifoper, &ponport.Ifspeed)
			target.PonPortsIfIndex[ponport.Ifindex] = &ponport
			target.PonPortsIfName[ponport.Ifname] = &ponport
			if target.Vendor == "Nokia" {
				nokPonId := GetOltPonIdForNokia(ponport.Ifindex)
				target.PonPortsNokiaPonId[nokPonId] = &ponport
			} else if target.Vendor == "ZTE" {
				target.PonPortsName[ponport.PonPort] = &ponport
			}
			ponport_cnt += 1
		}

		// load odn
		// rows2, err2 = db.Query(`select ponport, l1name, l1ratio, l1len, l2name, l2ratio, l2len
		// 									from odn
		// 									where oltname = $1`, target.Device)
		// if err2 != nil {
		// 	return nil, err2
		// }
		// for rows2.Next() {
		// 	odn := ODN{}
		// 	rows2.Scan(&odn.PonPort, &odn.L1Name, odn.L1Ratio, odn.L1Len, &odn.L2Name, odn.L2Ratio, odn.L2Len)
		// 	target.ODNs[odn.PonPort] = &odn
		// 	odn_cnt += 1
		// }

		targets = append(targets, target)
		device_cnt += 1
	}
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	log.Printf("loadTargetFromDb: return %d device, %d intf, %d ponport, %d odn", device_cnt, intf_cnt, ponport_cnt, odn_cnt)
	return targets, nil
}

func buildQuery(setting *AppSetting, colname string) (string, error) {
	// activehost := map[string]bool{
	// 	"tyb-pms-online-dc01.pms": true,
	// 	"tyb-pms-online-dc02.pms": true,
	// 	"tyb-pms-online-dc03.pms": true,
	// }
	activehost, err := zkGetActiveHost(setting)
	if err != nil {
		return "", err
	}
	log.Printf("activeHost = %v", activehost)

	hostname, _ := os.Hostname()
	agents := make([]AgentInfo, 0)
	for _, group := range setting.Collector.Groups {
		agent := AgentInfo{name: group.Name, nodes: make([]string, 0)}
		for _, node := range group.Nodes {
			is_active := activehost[node]
			if is_active {
				agent.nodes = append(agent.nodes, node)
			}
		}
		if len(agent.nodes) > 0 {
			for idx, node := range agent.nodes {
				if hostname == node {
					agent.cid = idx
					agents = append(agents, agent)
					break
				}
			}
		}
	}

	if len(agents) == 0 {
		return "", errors.New("no active resource, check pmsonlined service")
	}

	list := make([]string, 0)
	for _, agent := range agents {
		// (('x'|| md5(ip::text))::bit(32)::bigint %% %d = %d and coalesce(agent, 'default') = '%s')
		sql := fmt.Sprintf("(('x'|| md5(%s::text))::bit(32)::bigint %% %d = %d and coalesce(agent, 'default') = '%s')", colname, len(agent.nodes), agent.cid, agent.name)
		list = append(list, sql)
	}
	return strings.Join(list, " or "), nil
}

func saveTargetToJson(filename string, targets []SnmpTarget) error {
	t := time.Now()
	bytes, err := json.Marshal(targets)
	if err != nil {
		log.Printf("Error! %v", err)
		return err
	}
	fout, err := os.OpenFile(filename, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
	if err != nil {
		log.Printf("Error! %v", err)
		return err
	}
	defer fout.Close()
	fout.Write(bytes)
	log.Printf("saveTargetToJson: %d entries in %v", len(targets), time.Since(t))
	return nil
}

func loadTargetFromJson(filename string) ([]SnmpTarget, error) {
	var targets []SnmpTarget
	t := time.Now()
	content, _ := os.ReadFile(filename)
	err := json.Unmarshal(content, &targets)
	if err != nil {
		return nil, err
	}
	log.Printf("loadTargetFromJson: %s return %d entries in %v", filename, len(targets), time.Since(t))
	return targets, nil
}

func StartSnmpPoll(name string, configfile string, ptimeout int) error {
	t := time.Now()

	// settings
	config := loadSnmpPollConfig(configfile)
	// logInfo("settings", config)

	wg_init := sync.WaitGroup{}
	wg := sync.WaitGroup{}
	rl := ratelimit.New(config.Setting.RateLimit)
	ch := make(chan SnmpResult)

	// terminate process if processing time exceed timeout (second)
	var timer_cancel = make(chan bool)
	if ptimeout > 0 {
		go NewTimer(time.Duration(ptimeout)*time.Second, timer_cancel, ch)
	}

	// initialize level-db
	leveldb, err := NewLevelDB(config.Setting.LevelDbBaseDir, time.Duration(120)*time.Second)
	if err != nil {
		filepath, _ := filepath.Abs(config.Setting.LevelDbBaseDir)
		log.Printf("Error! Falied to open leveldb: %s [%v]", filepath, err)
		return err
	}
	// Cleanup expired data
	// *** This function may take sometimes ***
	wg_init.Add(1)
	tstamp := time.Now().Add(-time.Duration(24) * time.Hour)
	go leveldb.Cleanup(tstamp, &wg_init)
	defer leveldb.db.Close()

	wg_init.Wait()
	log.Printf("Initialize is done...")

	filepath, _ := filepath.Abs(config.Setting.LevelDbBaseDir)
	log.Printf("Loaded leveldb: %s", filepath)

	// load targets
	targets, err := loadTarget(name, config)
	if err != nil {
		return err
	}

	// start poller
	for _, target := range targets {
		wg.Add(1)
		go NewSnmpPoller(&wg, rl, config, target, ch)
	}

	// start writer
	wg.Add(1)
	go NewOutputWriter(&wg, config, &targets, leveldb, ch)

	log.Printf("working...")

	// wait for all goroutine
	wg.Wait()

	// cancel timer
	if ptimeout > 0 {
		timer_cancel <- true
	}
	log.Printf("completed: successful in %v", time.Since(t))
	return nil
}

func NewTimer(timeout time.Duration, stop chan bool, ch chan SnmpResult) {
	start := time.Now()
	for {
		select {
		case cancel := <-stop:
			if cancel {
				// log.Printf("Timer cancelled")
				return
			}
		default:
			if time.Since(start) < timeout {
				time.Sleep(1 * time.Second)
			} else {
				ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Status: "timedout"}
				time.Sleep(time.Duration(1) * time.Second)
				log.Printf("completed: timedout ptime=%s, timeout=%s", time.Since(start), timeout)
				os.Exit(1)
				return
			}
		}
	}
}

func NewOutputWriter(wg *sync.WaitGroup, config *SnmpPollConfig, targets *[]SnmpTarget, leveldb *DeltaDB, ch chan SnmpResult) {
	defer wg.Done()

	// pollStatusMap := make(map[string]*PollStatus) // key = network
	// pollStatusErr := make([]PollStatusErr, 0, 100)
	// cnt_ok := 0
	// cnt_err := 0

	// initialize output file
	files := make(map[string]*os.File)
	for _, out := range config.SnmpPoll.Output {
		key := fmt.Sprintf("%s.%s", out.Name, out.Format)
		fp, ok := files[key]
		if !ok {
			fp := out.openFile(config)
			files[key] = fp
			defer out.closeFile()
		} else {
			// multiple output sharing same file so we must set file pointer as well
			out.fp = fp
		}
	}

	pending := make(map[string]SnmpTarget)
	for _, target := range *targets {
		pending[target.IP] = target
	}

	for i := 0; i < len(*targets); i++ {
		result, ok := <-ch
		if !ok {
			// channel was closed
			log.Fatal("Error! channel is closed")
		}
		log.Printf("got result...")
		if result.Target.IP != "" {
			delete(pending, result.Target.IP)
			if result.Status == "success" {
				tables := mapPollTable(config, leveldb, &result)
				// logInfo("tables", tables)

				for _, tb := range tables {
					tb.writeFile(config, &result)
				}
			}
		} else {
			for _, target := range pending {
				log.Printf("Failed target: %v", target.IP)
			}
			log.Printf("Failed total: %d", len(pending))
		}
	}

	// savePollStatus(config.Setting.DbConnection, pollStatusMap, pollStatusErr, cnt_ok, cnt_err)
}

func NewSnmpPoller(wg *sync.WaitGroup, rl ratelimit.Limiter, config *SnmpPollConfig, target SnmpTarget, ch chan SnmpResult) {
	// rate-limit control
	rl.Take()
	defer wg.Done()

	// ping device if IcmpCount > 0, otherwise, icmp ping is disabled
	if target.IcmpCount > 0 {
		icmpResult := IcmpPing(&target, target.IcmpCount, time.Duration(target.IcmpInterval)*time.Millisecond, time.Duration(target.IcmpTimeout)*time.Millisecond)
		if !icmpResult.IsReachable() {
			log.Printf("Error! %s icmp ping error: %v", target.IP, icmpResult.ErrMsg())
			ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: target, Status: "icmp-ping-timeout"}
			return
		}
	}

	SnmpGetTable(config, &target, ch)
}

func SnmpGetTable(config *SnmpPollConfig, target *SnmpTarget, ch chan SnmpResult) {
	req := config.mapSnmpBulkGetReq(target)
	if req == nil {
		log.Fatalf("Error! target contains unsupported device: %s, vendor=%s, model=%s", target.IP, target.Vendor, target.Model)
	}
	allSnmpVars := make([]SnmpVar, 0)
	for _, job := range req.Jobs {
		if job.RequestStrategy == "column" {
			snmpVars, err := SnmpGetTableByColumn(target, &job, ch)
			if err != nil {
				ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: *target, Status: err.Error()}
				return
			}
			allSnmpVars = append(allSnmpVars, snmpVars...)

		} else if job.RequestStrategy == "row" {
			snmpVars, err := SnmpGetTableByRow(target, &job, ch)
			if err != nil {
				ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: *target, Status: err.Error()}
				return
			}
			allSnmpVars = append(allSnmpVars, snmpVars...)

		} else if job.RequestStrategy == "get" {
			snmpVars, err := SnmpGetOids(target, &job, ch)
			if err != nil {
				ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: *target, Status: err.Error()}
				return
			}
			allSnmpVars = append(allSnmpVars, snmpVars...)

		}
	}
	ch <- SnmpResult{CollectTime: JsonTime(time.Now()), Target: *target, Status: "success", SnmpVars: allSnmpVars}
}

func SnmpGetOids(target *SnmpTarget, job *SnmpBulkGetJob, ch chan SnmpResult) ([]SnmpVar, error) {
	t := time.Now()
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(job.Timeout) * time.Second, // time.Duration(target.Timeout) * time.Second,
		Retries:            job.Retries,
		ExponentialTimeout: job.ExpTime,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("%s [%s] Error! snmp_connect: %v", target.IP, job.Name, err)
		return nil, err
	}
	defer params.Conn.Close()

	snmpVars := make([]SnmpVar, 0)
	req_oid_batchs := job.CreateOidList(target)
	for _, req_oids := range req_oid_batchs {
		collectTime := time.Now()
		result, err := params.Get(req_oids)
		if err != nil {
			return nil, err
		}
		for _, variable := range result.Variables {
			snmpOid := job.mapSnmpOid(&variable)
			if snmpOid == nil {
				log.Printf("Error! %v", variable.Name)
				continue
			}
			snmpVar := job.MapSnmpVar(target, snmpOid, collectTime, variable)
			if snmpVar == nil {
				// Unknown Interface
				continue
			}
			snmpVars = append(snmpVars, *snmpVar)
			// log.Printf("%-30s | %-10s | %-15s | %-10s | %-5s | %v", snmpOid.Name, variable.Type, snmpVar.RowIndex, snmpVar.IfIndex, snmpVar.OntId, variable.Value)
		}
	}
	log.Printf("%s [%s] return in %v", target.IP, job.Name, time.Since(t))
	return snmpVars, nil
}

func SnmpGetTableByRow(target *SnmpTarget, job *SnmpBulkGetJob, ch chan SnmpResult) ([]SnmpVar, error) {
	t := time.Now()
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(job.Timeout) * time.Second, // time.Duration(target.Timeout) * time.Second,
		Retries:            job.Retries,
		ExponentialTimeout: job.ExpTime,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("%s [%s] Error! snmp_connect: %v", target.IP, job.Name, err)
		return nil, err
	}
	defer params.Conn.Close()

	snmpVars := make([]SnmpVar, 0)
	req_oid_batchs := job.CreateOidList(target)
	for _, req_oids := range req_oid_batchs {
		collectTime := time.Now()
		result, err := params.Get(req_oids)
		if err != nil {
			return nil, err
		}
		for _, variable := range result.Variables {
			snmpOid := job.mapSnmpOid(&variable)
			if snmpOid == nil {
				log.Printf("Error! %v", variable.Name)
				continue
			}
			snmpVar := job.MapSnmpVar(target, snmpOid, collectTime, variable)
			if snmpVar == nil {
				// Unknown Interface
				continue
			}
			snmpVars = append(snmpVars, *snmpVar)
			// log.Printf("%-30s | %-10s | %-15s | %-10s | %-5s | %v", snmpOid.Name, variable.Type, snmpVar.RowIndex, snmpVar.IfIndex, snmpVar.OntId, variable.Value)
		}
	}
	log.Printf("%s [%s] return in %v", target.IP, job.Name, time.Since(t))
	return snmpVars, nil
}

func SnmpGetTableByColumn(target *SnmpTarget, job *SnmpBulkGetJob, ch chan SnmpResult) ([]SnmpVar, error) {
	t := time.Now()
	params := &gosnmp.GoSNMP{
		Target:             target.IP,
		Port:               target.Port,
		Version:            target.Version,
		Community:          target.Community,
		Timeout:            time.Duration(job.Timeout) * time.Second, // time.Duration(target.Timeout) * time.Second,
		Retries:            job.Retries,
		ExponentialTimeout: job.ExpTime,
		Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("%s [%s] Error! snmp_connect: %v", target.IP, job.Name, err)
		return nil, err
	}
	defer params.Conn.Close()

	maxRepetition := job.getMaxRepetition(target)
	snmpVars := make([]SnmpVar, 0)
	for _, snmpOid := range job.Oids {
		req_oid := snmpOid.Oid
		nonRepeaters := job.getNonRepeaters(target, snmpOid)
		cnt := 0
		for {
			cnt += 1
			collectTime := time.Now()

			result, err := params.GetBulk([]string{req_oid}, nonRepeaters, maxRepetition)
			if err != nil {
				snmp_cmd := fmt.Sprintf("snmpbulkget -v2c -c %s %s -t %d -r %d -Cn%d -Cr%d %s",
					target.Community, target.IP, job.Timeout, job.Retries, nonRepeaters, maxRepetition, req_oid)
				log.Printf("Error! %v, {%s}", err, snmp_cmd)
				return nil, err
			}
			for _, variable := range result.Variables {
				if strings.HasPrefix(variable.Name, snmpOid.Oid+".") {
					snmpVar := job.MapSnmpVar(target, &snmpOid, collectTime, variable)
					if snmpVar == nil {
						// Unknown Interface
						continue
					}
					snmpVars = append(snmpVars, *snmpVar)
					// log.Printf("%-30s | %-10s | %-15s | %-10s | %-5s | %v", snmpOid.Name, variable.Type, snmpVar.RowIndex, snmpVar.IfIndex, snmpVar.OntId, variable.Value)
				}
			}
			if isEndOfOid(&result.Variables, snmpOid.Oid) {
				break
			}
			req_oid = result.Variables[len(result.Variables)-1].Name
		}
	}
	log.Printf("%s [%s] return in %v", target.IP, job.Name, time.Since(t))
	return snmpVars, nil
}

func mapPollTable(config *SnmpPollConfig, leveldb *DeltaDB, result *SnmpResult) map[string]*PollTable {
	// s, _ := json.MarshalIndent(result, "", " ")
	// log.Printf("%v", string(s))
	// key = objType
	tables := make(map[string]*PollTable)
	for _, snmpVar := range result.SnmpVars {
		tb, ok := tables[snmpVar.ObjType]
		if !ok {
			tb = &PollTable{ObjType: snmpVar.ObjType, Rows: make(map[string]*PollRecord)}
			tables[snmpVar.ObjType] = tb
		}
		tb.add(snmpVar)
	}

	for _, tb := range tables {
		transform := config.getTransform(tb.ObjType)
		if transform == nil {
			// log.Printf("Warn! no transform logic for: " + tb.ObjType)
			continue
		}

		for _, row := range tb.Rows {
			if len(transform.Fields) > 0 {
				transform.computeRow(config, leveldb, &result.Target, tb, row)
			}
			transform.transform(&result.Target, row)
		}
	}
	return tables
}

func (transform *Transform) computeRow(config *SnmpPollConfig, leveldb *DeltaDB, target *SnmpTarget, tb *PollTable, row *PollRecord) {
	// log.Printf("computeRow: %s|%v", row.RowId, row.Values)
	key := fmt.Sprintf("%s#%s#%s", tb.ObjType, target.IP, row.RowId)
	saved1, err := leveldb.GetValue([]byte(key))
	if err != nil {
		// NotFound --> New Interface: save new value, no delta value
		saved2 := newSavedValue(row.CollectTime, row)
		dberr := leveldb.PutValue([]byte(key), saved2)
		if dberr != nil {
			log.Fatalf("Error! %v", dberr)
		}
		// log.Printf("delta: %s [new], t1 = %v", key, saved2.CollectTime.Format(DateTimeFormat))
	} else {
		// Found --> compute delta
		saved2 := newSavedValue(row.CollectTime, row)
		if saved1.isExpired(saved2, config.SnmpPoll.PollInt, config.SnmpPoll.ExpiredMultiplier) {
			// expired data: save new value, do not emit delta
			leveldb.PutValue([]byte(key), saved2)
			log.Printf("delta: %s [expired], t1 = %v, t2 = %v", key, saved1.CollectTime.Format(DateTimeFormat), saved2.CollectTime.Format(DateTimeFormat))
		} else {
			// check if counter was reset
			if saved1.isReset(saved2) {
				// ifCounterDiscontinuityTime changed
				// saved new value and do not emit delta
				leveldb.PutValue([]byte(key), saved2)
				log.Printf("delta: %s [reset]", key)

			} else {
				// ok: save new value and emit delta
				leveldb.PutValue([]byte(key), saved2)
				computeDelta(target, &transform.Fields, row, saved1, saved2)
				// log.Printf("delta: %s [ok]", key)
			}
		}
	}
}

func newSavedValue(collectTime JsonTime, row *PollRecord) *SavedValue {
	saved := SavedValue{CollectTime: time.Time(collectTime), Values: make(map[string]interface{})}
	for name, val := range row.Values {
		saved.Values[name] = val
	}
	return &saved
}

func computeDelta(target *SnmpTarget, tfFields *[]TransformField, row *PollRecord, saved1 *SavedValue, saved2 *SavedValue) {
	meas := int(time.Time(saved2.CollectTime).Sub(time.Time(saved1.CollectTime)).Seconds())
	row.Meas = meas
	row.ReportedTime = JsonTime(saved1.CollectTime)
	// delta := DeltaEntry{
	// 	CollectTime: JsonTime(saved1.CollectTime),
	// 	Meas:        meas,
	// 	Key:         row.RowId,
	// 	IfIndex:     row.IfIndex,
	// 	Values:      make(map[string]*DeltaValue),
	// }

	for _, field := range *tfFields {
		value1, ok1 := saved1.Values[field.Name]
		value2, ok2 := saved2.Values[field.Name]

		if ok1 && ok2 {
			type1 := reflect.TypeOf(value1)
			type2 := reflect.TypeOf(value2)
			if type1 == type2 {
				switch v := value1.(type) {
				case uint64:
					switch field.Mode {
					case "latest":
						// delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "latest", Value1: value1, Value2: value2, Delta: value2}
						row.Values[field.Save] = value2
					default:
						// mode = "delta" or empty

						// There's issue with FTTx ZTE for pontraffic60m
						// counters: zte_in_octets, zte_out_octets, zte_in_octets1490, zte_out_octets1490, zte_in_octets1490, zte_out_octets1577
						// 1.) counter suddendly reset to 0 then increase in subsequence polling
						// 2.) counter suddently jump to exceed 100% then decrease in subsquence polling
						var limit_ptr *uint64
						if row.Fields.IfSpeed > 0 {
							limit_ptr = getLimit(&field, meas, row.Fields.IfSpeed)
						}
						deltaVal, deltaFlag := computeDeltaUint64(value1.(uint64), value2.(uint64), &UINT64_MAX, limit_ptr)
						// delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: deltaFlag, Value1: value1, Value2: value2, Delta: deltaVal}
						row.Values[field.Prev] = value1.(uint64)
						row.Values[field.Curr] = value2.(uint64)
						row.Values[field.Save] = deltaVal

						// debug BKK41015GO0|10.239.45.9|285278467|gpon_1/1/3
						if target.Vendor == "ZTE" && target.Network == "FTTx" &&
							(field.Name == "zte_in_octets" ||
								field.Name == "zte_out_octets" ||
								field.Name == "zte_in_octets1490" ||
								field.Name == "zte_out_octets490" ||
								field.Name == "zte_in_octets1577" ||
								field.Name == "zte_out_octets1577") {
							log.Printf("trace: %v|%v|%v|%v|%v|%v|%v|%v|%v", target.IP, row.Fields.PonPort, row.Fields.IfIndex, field.Name, value1, value2, limit_ptr, deltaVal, deltaFlag)
						}
					}
				case int64:
					switch field.Mode {
					case "latest":
						// delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "latest", Value1: value1, Value2: value2, Delta: value2}
						row.Values[field.Save] = value2
					default:
						// mode = "delta" or empty
						var max_ptr *int64
						var limit_ptr *int64
						if field.Max != nil {
							max := int64(*field.Max)
							max_ptr = &max
						}
						if field.Limit != nil {
							limit := int64(*field.Limit)
							limit_ptr = &limit
						}
						deltaVal, _ := computeDeltaInt64(value1.(int64), value2.(int64), max_ptr, limit_ptr)
						// delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: deltaFlag, Value1: value1, Value2: value2, Delta: deltaVal}
						row.Values[field.Prev] = value1.(int64)
						row.Values[field.Curr] = value2.(int64)
						row.Values[field.Save] = deltaVal
					}
				case string:
					// ignore "mode", always return latest value
					// delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "ok", Value1: value1, Value2: value2, Delta: value2.(string)}
					row.Values[field.Save] = value2.(string)
				default:
					log.Printf("Error! %s, ifIndex=%s: ComputeDelta Not Support %v, %v, %v, %v", target.IP, row.Fields.IfIndex, field.Name, v, type1, type2)
				}
			} else {
				// different type
				log.Printf("Error! %s, ifIndex=%s: Different Type %v, value1 = %v {%v}, value2 = %v {%v}", target.IP, row.Fields.IfIndex, field.Name, value1, type1, value2, type2)
			}
		}
	}
}

func logInfo(name string, obj interface{}) {
	s, _ := json.MarshalIndent(obj, "", " ")
	log.Printf("%s: %s", name, s)
}
