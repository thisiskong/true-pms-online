package snmplib

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"time"

	"go.uber.org/ratelimit"
)

func timer_start(timeout time.Duration, stop chan bool) {
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
				log.Printf("Timer exceeded, ptime=%s, timeout=%s", time.Since(start), timeout)
				os.Exit(1)
				return
			}
		}
	}
}

func StartSnmpDiscovery(discfile string, discid int, ptimeout int) error {
	var wg sync.WaitGroup
	tasksDone := make(chan SnmpResult)

	// terminate process if processing time exceed timeout (second)
	var timer_cancel = make(chan bool)
	if ptimeout > 0 {
		go timer_start(time.Duration(ptimeout)*time.Second, timer_cancel)
	}

	if discfile != "" {
		task, err := LoadDiscoveryConfigById(discfile, discid)
		if err != nil {
			return err
		}

		// create rate limiter
		globalRateLimit := ratelimit.New(task.Setting.RateLimit)
		topoRateLimits := make(map[string]ratelimit.Limiter)
		for _, disc := range task.Discovery.Discoveries {
			_, ok := topoRateLimits[disc.Topology]
			if !ok {
				val, ok := task.Setting.TopologyRateLimit[disc.Topology]
				if ok {
					topoRateLimits[disc.Topology] = ratelimit.New(val)
				} else {
					topoRateLimits[disc.Topology] = ratelimit.New(task.Setting.TopologyRateLimitDefault)
				}
			}
		}

		// mapper
		mapper, err := NewMapper(task.Setting)
		if err != nil {
			log.Panic(err)
		}

		// lookup service
		lookupService, err := NewLookupService(task)
		if err != nil {
			log.Panic(err)
		}

		// lldp mapper
		lldpMapper := NewLldpMapper(task, lookupService)

		wg.Add(1)
		go NewDiscoveryProcessor(task, &wg, tasksDone)
		for _, disc := range task.Discovery.Discoveries {
			for _, target := range disc.SnmpTargets {
				wg.Add(1)
				topoRateLimit := topoRateLimits[disc.Topology]
				go SnmpDiscovery(globalRateLimit, topoRateLimit, mapper, lookupService, lldpMapper, task, disc, target, &wg, tasksDone)
			}
		}
	}

	// wait for all goroutine
	wg.Wait()

	// cancel timer
	if ptimeout > 0 {
		timer_cancel <- true
	}
	return nil
}

func StartSnmpDiscoveryByEngine(discfile string, discid int, devicefile string) error {
	if discfile == "" {
		return fmt.Errorf("error: missing discfile")
	}

	task, err := LoadDiscoveryConfigById(discfile, discid)
	if err != nil {
		return err
	}

	if len(task.Discovery.Discoveries) == 0 {
		return fmt.Errorf("error: invalid discid")
	}

	// load devices.json
	var devices []Device
	content, _ := os.ReadFile(devicefile)
	err = json.Unmarshal(content, &devices)
	if err != nil {
		return err
	}
	log.Printf("load %v return %d entries", devicefile, len(devices))
	ptime := time.Now()

	// mapper
	mapper, err := NewMapper(task.Setting)
	if err != nil {
		log.Panic(err)
	}

	// lookup service
	lookupService, err := NewLookupService(task)
	if err != nil {
		log.Panic(err)
	}

	// lldp mapper
	// lldpMapper := NewLldpMapper(task, lookupService)

	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable&connect_timeout=10"
	db, err := sql.Open("postgres", task.Setting.DbConnection)
	if err != nil {
		log.Panic(err)
	}
	defer db.Close()

	for _, deviceInst := range devices {
		// disc.go - snmp2Device
		mapper.SetProvince(&deviceInst, &lookupService.ProvinceCode)
		mapper.SetDiscoveryFields(&deviceInst, &task.Discovery.Discoveries[0])
		mapper.MapDevice(&deviceInst)
		mapper.SetIfTopologyIfDstIp(&deviceInst, lookupService)
		mapper.MapIntfs(&deviceInst)

		// FTTx (after mapping.js)
		if deviceInst.Network == "FTTx" {
			// Set L1 Splitter
			MapL1Splitter(task, lookupService, &deviceInst)

			// Set OLT Uplink moduleclass & vendorPn
			// set_fttx_intf_moduleclass(task, &snmpResult.Target, &deviceInst)

			// Set OLT PonPort moduleclass & vendorPn
			// set_fttx_ponport_moduleclass(task, &snmpResult.Target, &deviceInst)

			// Board
			// set_fttx_board(task, &snmpResult.Target, &deviceInst, mapper)
			mapper.MapBoards(&deviceInst, nil)
		}

		// disc.go
		saveDeviceInstance(db, &deviceInst, ptime)
	}

	// // update lldp from OLT to uplink device
	// err = lldpMapper.update_lldp_uplink(db)
	// if err != nil {
	// 	log.Printf("Error! %v", err)
	// }

	// update to db
	tx, err := db.Begin()
	if err != nil {
		log.Printf("Error! %v", err)
	}

	tx.Commit()
	return nil
}

func StartSnmpDiscoveryByIp(discfile string, discip string, ptimeout int) error {
	var wg sync.WaitGroup
	tasksDone := make(chan SnmpResult)

	// terminate process if processing time exceed timeout (second)
	var timer_cancel = make(chan bool)
	if ptimeout > 0 {
		go timer_start(time.Duration(ptimeout)*time.Second, timer_cancel)
	}

	if discfile == "" {
		return fmt.Errorf("error: missing discfile")
	}

	task, err := LoadDiscoveryConfigByIp(discfile, discip)
	if err != nil {
		return err
	}

	if task == nil {
		return fmt.Errorf("error: undefined discovery rule for ip: %v", discip)
	}

	// create rate limiter
	globalRateLimit := ratelimit.New(task.Setting.RateLimit)
	topoRateLimits := make(map[string]ratelimit.Limiter)
	for _, disc := range task.Discovery.Discoveries {
		_, ok := topoRateLimits[disc.Topology]
		if !ok {
			val, ok := task.Setting.TopologyRateLimit[disc.Topology]
			if ok {
				topoRateLimits[disc.Topology] = ratelimit.New(val)
			} else {
				topoRateLimits[disc.Topology] = ratelimit.New(task.Setting.TopologyRateLimitDefault)
			}
		}

		// mapper
		mapper, err := NewMapper(task.Setting)
		if err != nil {
			log.Panic(err)
		}

		// lookup service
		lookupService, err := NewLookupService(task)
		if err != nil {
			log.Panic(err)
		}

		// lldp mapper
		lldpMapper := NewLldpMapper(task, lookupService)

		wg.Add(1)
		go NewDiscoveryProcessor(task, &wg, tasksDone)
		for _, disc := range task.Discovery.Discoveries {
			for _, target := range disc.SnmpTargets {
				wg.Add(1)
				topoRateLimit := topoRateLimits[disc.Topology]
				go SnmpDiscovery(globalRateLimit, topoRateLimit, mapper, lookupService, lldpMapper, task, disc, target, &wg, tasksDone)
			}
		}
	}

	// wait for all goroutine
	wg.Wait()

	// cancel timer
	if ptimeout > 0 {
		timer_cancel <- true
	}
	return nil
}

func PollTraffic(polltype string, configfile string, deltafile string, tsdbfile string, datalakefile string, offlinedir string, pollint int, ptimeout int) error {
	// polltype = traffic5m or traffic15m or traffic60m
	var wg_init sync.WaitGroup
	var wg sync.WaitGroup
	var db *DeltaDB

	// terminate process if processing time exceed timeout (second)
	var timer_cancel = make(chan bool)
	if ptimeout > 0 {
		go timer_start(time.Duration(ptimeout)*time.Second, timer_cancel)
	}

	tasksDone := make(chan SnmpResult)
	task := LoadPollTrafficConfig(configfile)

	// load SnmpTarget
	// *** This function will take sometimes ***
	wg_init.Add(1)
	go LoadSnmpTarget(&wg_init, task, pollint)

	// LevelDB
	if task.PollTraffic.Delta != nil && deltafile != "" {
		ldbname := fmt.Sprintf("level-%s.db", polltype)
		ldbpath := filepath.Join(task.Setting.LevelDbBaseDir, ldbname)

		var err error
		db, err = NewLevelDB(ldbpath, time.Duration(120)*time.Second)
		if err != nil {
			filepath, _ := filepath.Abs(ldbpath)
			log.Printf("Error! Falied to open leveldb: %s [%v]", filepath, err)
			return err
		}
		filepath, _ := filepath.Abs(ldbpath)
		log.Printf("Loaded leveldb: %s", filepath)

		// Cleanup expired data
		// *** This function may take sometimes ***
		wg_init.Add(1)
		tstamp := time.Now().Add(-time.Duration(24) * time.Hour)
		go db.Cleanup(tstamp, &wg_init)
		defer db.db.Close()
	}

	wg_init.Wait()
	log.Printf("Initialize is done...")

	// create rate limiter
	globalRateLimit := ratelimit.New(task.Setting.RateLimit)
	topoRateLimits := make(map[string]ratelimit.Limiter)
	for _, target := range task.SnmpTargets {
		_, ok := topoRateLimits[target.Topology]
		if !ok {
			val, ok := task.Setting.TopologyRateLimit[target.Topology]
			if ok {
				topoRateLimits[target.Topology] = ratelimit.New(val)
			} else {
				topoRateLimits[target.Topology] = ratelimit.New(task.Setting.TopologyRateLimitDefault)
			}
		}
	}

	wg.Add(1)
	go NewSnmpGetProcessor(task, polltype, deltafile, tsdbfile, datalakefile, offlinedir, pollint, &wg, db, tasksDone, len(task.SnmpTargets))
	for _, target := range task.SnmpTargets {
		wg.Add(1)
		if task.PollTraffic.IfTable.TableOid != "" {
			topoRateLimit := topoRateLimits[target.Topology]
			go SnmpPollTraffic(globalRateLimit, topoRateLimit, task.Setting, task, target, &wg, tasksDone)

			// } else if task.PollTraffic.GetOid != nil {
			// 	go GetSnmpOid(rl, task.Setting, task.GetOid, target, &wg, tasksDone)

		} else {
			log.Fatalf("Error! Invalid config [%s]", reflect.TypeOf(task))
		}
	}

	// wait for all goroutine
	wg.Wait()

	// cancel timer
	if ptimeout > 0 {
		timer_cancel <- true
	}
	return nil
}
