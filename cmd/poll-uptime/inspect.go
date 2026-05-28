package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/thisiskong/true-pms-online/internal/config"
	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/poller"
	"github.com/thisiskong/true-pms-online/internal/snmp"
	"github.com/thisiskong/true-pms-online/internal/state"
)

func runInspect(cfg *config.Config, ip string, log *slog.Logger) {
	store, err := state.NewLevelDBStore(cfg.LevelDBPath)
	if err != nil {
		fmt.Printf("ERROR: open leveldb: %v\n", err)
		return
	}
	defer store.Close()

	// 1 — dump persisted state
	st, err := store.Get(ip)
	if err != nil {
		fmt.Printf("ERROR: read state: %v\n", err)
		return
	}
	fmt.Println("=== State (LevelDB) ===")
	stateJSON, _ := json.MarshalIndent(st, "", "  ")
	fmt.Println(string(stateJSON))

	// 2 — find device in cache for SNMP credentials
	dev := findDevice(cfg, ip)
	if dev == nil {
		fmt.Printf("\nWARN: IP %s not found in device cache — using defaults (community=public, port=161)\n", ip)
		d := device.Device{IP: ip, Port: cfg.DefaultPort, SNMPVersion: 2, Community: "public"}
		dev = &d
	}

	// 3 — live SNMP GET (all 3 OIDs)
	fmt.Println("\n=== Live SNMP GET ===")
	client := snmp.NewGoSNMPClient(cfg.SNMPTimeout, cfg.SNMPRetries)
	ctx, cancel := context.WithTimeout(context.Background(), cfg.SNMPTimeout*2)
	defer cancel()

	values, absent, err := client.GetWithAbsent(ctx, *dev, snmp.ProbeOIDs)
	if err != nil {
		fmt.Printf("ERROR: snmp get failed: %v\n", err)
		return
	}

	printOID("snmpEngineBoots", snmp.OIDEngineBoots, values, absent)
	printOID("snmpEngineTime ", snmp.OIDEngineTime, values, absent)
	printOID("sysUptime      ", snmp.OIDSysUptime, values, absent)

	// 4 — run detection algorithm
	fmt.Println("\n=== Detection Result ===")
	now := time.Now().UTC()

	detectCfg := poller.DetectConfig{
		RolloverThresholdSeconds:  cfg.RolloverThresholdSeconds,
		MaxValueStreakThreshold:   cfg.MaxValueStreakThreshold,
		GapRebootThresholdSeconds: cfg.GapRebootThresholdSeconds,
	}

	engineAbsent := absent[snmp.OIDEngineBoots] || absent[snmp.OIDEngineTime]

	if !st.EngineProbed {
		fmt.Println("Path        : not yet probed (no state)")
	} else if st.UseEngineOIDs && !engineAbsent {
		fmt.Println("Path        : A (snmpEngineBoots)")
		boots := values[snmp.OIDEngineBoots]
		engTime := values[snmp.OIDEngineTime]
		fmt.Printf("prev boots  : %d   curr boots : %d\n", st.LastEngineBoots, boots)
		fmt.Printf("prev engTime: %d   curr engTime: %d\n", st.LastEngineTime, engTime)
		result, _ := poller.DetectRebootEngine(st, boots, engTime, now, detectCfg)
		printResult(result)
	} else {
		if st.UseEngineOIDs && engineAbsent {
			fmt.Println("Path        : A→B (engine OIDs disappeared — firmware downgrade?)")
		} else {
			fmt.Println("Path        : B (sysUptime)")
		}
		curr := values[snmp.OIDSysUptime]
		fmt.Printf("prev uptime : %d (0x%08X)\n", st.LastSysUptime, st.LastSysUptime)
		fmt.Printf("curr uptime : %d (0x%08X)\n", curr, curr)
		fmt.Printf("MaxStreak   : %d → %d  (threshold: %d)\n",
			st.MaxValueStreak, st.MaxValueStreak+1, cfg.MaxValueStreakThreshold)
		wallElapsed := now.Sub(st.LastWallClock).Seconds()
		if st.LastWallClock.IsZero() {
			fmt.Println("LastWallClock: zero (first poll)")
		} else {
			fmt.Printf("wall elapsed: %.0fs since last poll at %s\n",
				wallElapsed, st.LastWallClock.Format("2006-01-02T15:04:05"))
		}
		result, _ := poller.DetectRebootUptime(st, curr, now, detectCfg)
		printResult(result)
	}
}

func printOID(label, oid string, values map[string]uint32, absent map[string]bool) {
	if absent[oid] {
		fmt.Printf("%-16s: absent (noSuchObject)\n", label)
	} else if v, ok := values[oid]; ok {
		fmt.Printf("%-16s: %d  (0x%08X)\n", label, v, v)
	} else {
		fmt.Printf("%-16s: not returned\n", label)
	}
}

func printResult(r poller.RebootResult) {
	if r.IsReboot {
		suspected := ""
		if r.IsSuspected {
			suspected = "  [SUSPECTED — gap inferred]"
		}
		fmt.Printf("Decision    : REBOOT detected  method=%s%s\n", r.DetectionMethod, suspected)
		fmt.Printf("prev=%d  curr=%d\n", r.PrevValue, r.CurrValue)
		if !r.EstimatedBoot.IsZero() {
			fmt.Printf("estimatedBoot: %s\n", r.EstimatedBoot.Format("2006-01-02T15:04:05"))
		}
	} else {
		fmt.Println("Decision    : NO REBOOT")
	}
}

func findDevice(cfg *config.Config, ip string) *device.Device {
	cache := device.NewFileCache(cfg.DeviceCacheFile)
	devices, err := cache.LoadFromCache()
	if err != nil {
		return nil
	}
	for _, d := range devices {
		if d.IP == ip {
			dev := d
			return &dev
		}
	}
	return nil
}
