package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"runtime/pprof"
	"strings"

	snmplib "true-pms-online/internal/snmplib"
	snmplib2 "true-pms-online/internal/snmplib2"

	"github.com/akamensky/argparse"
)

func LocalAddrList() {
	ifaces, err := net.Interfaces()
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	for _, i := range ifaces {
		addrs, err := i.Addrs()
		if err != nil {
			log.Fatalf("Error! %v", err)
		}
		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}
			log.Printf("ip=%v", ip)
		}
	}
}

func main() {
	// Create new parser object
	parser := argparse.NewParser("SnmpTk", "Snmp Toolkit")
	name := parser.String("", "name", &argparse.Options{Required: false, Help: "Name"})
	poll := parser.Int("", "poll", &argparse.Options{Required: false, Default: 900, Help: "Poll Interval"})

	disc := parser.String("", "disc", &argparse.Options{Required: false, Help: "Snmp Discovery"})
	discid := parser.Int("", "discid", &argparse.Options{Required: false, Default: -1, Help: "Snmp Discovery Rule Id"})
	discip := parser.String("", "discip", &argparse.Options{Required: false, Help: "Snmp Discovery IP"})
	devicefile := parser.String("", "devicefile", &argparse.Options{Required: false, Help: "Discovery using Device File"})

	snmpget := parser.String("", "snmpget", &argparse.Options{Required: false, Help: "Snmp Get"})
	snmppoll := parser.String("", "snmppoll", &argparse.Options{Required: false, Help: "Snmp Poll"})
	deltafile := parser.String("", "delta", &argparse.Options{Required: false, Help: "Delta file"})
	tsdbfile := parser.String("", "tsdb", &argparse.Options{Required: false, Help: "TSDB file"})
	datalakefile := parser.String("", "datalake", &argparse.Options{Required: false, Help: "Datalake file"})
	offlinedir := parser.String("", "offline", &argparse.Options{Required: false, Help: "Device Offline output path"})
	ptimeout := parser.Int("", "timeout", &argparse.Options{Required: false, Default: -1, Help: "Process Timeout in second"})

	debug_snmp := parser.Flag("", "debug-snmp", &argparse.Options{Required: false, Default: false, Help: "Turn-on snmp debug log"})
	debug := parser.Flag("", "debug", &argparse.Options{Required: false, Default: false, Help: "Turn-on debug log"})
	cpuprofile := parser.String("", "cpuprofile", &argparse.Options{Required: false, Help: "Turn-on CPU Profile"})

	// log to stdout
	log.SetOutput(os.Stdout)

	// Parse input
	log.Println(strings.Join(os.Args, " "))
	err := parser.Parse(os.Args)
	if err != nil {
		// In case of error print error and print usage
		// This can also be done by passing -h or --help flags
		fmt.Print(parser.Usage(err))
		os.Exit(1)
	}

	if *debug_snmp {
		snmplib.SnmpDebugEnable()
	}

	if *debug {
		snmplib.DebugEnable()
	}

	if *cpuprofile != "" {
		f, err := os.Create(*cpuprofile)
		if err != nil {
			log.Fatal(err)
		}
		pprof.StartCPUProfile(f)
		defer pprof.StopCPUProfile()
	}

	if *disc != "" {
		if *discip != "" {
			// snmptk --disc etc/disc.yml --discip <ip>
			err := snmplib.StartSnmpDiscoveryByIp(*disc, *discip, *ptimeout)
			if err != nil {
				log.Fatalf("Error! %v", err)
			}

		} else if *discid != -1 {

			if *devicefile != "" {
				// engine = nokia-altiplano
				// snmptk --disc etc/disc.yml --discid <discid> --devicefile <devices.json>
				err := snmplib.StartSnmpDiscoveryByEngine(*disc, *discid, *devicefile)
				if err != nil {
					log.Fatalf("Error! %v", err)
				}
			} else {
				// snmptk --disc etc/disc.yml --discid <discid>
				err := snmplib.StartSnmpDiscovery(*disc, *discid, *ptimeout)
				if err != nil {
					log.Fatalf("Error! %v", err)
				}
			}
		} else if *discid == -1 {
			// snmptk --disc etc/disc.yml
			err := snmplib.StartSnmpDiscovery(*disc, *discid, *ptimeout)
			if err != nil {
				log.Fatalf("Error! %v", err)
			}
		}

	} else if *snmpget != "" {
		err := snmplib.PollTraffic(*name, *snmpget, *deltafile, *tsdbfile, *datalakefile, *offlinedir, *poll, *ptimeout)
		if err != nil {
			log.Fatalf("Error! %v", err)
		}

	} else if *snmppoll != "" {
		err := snmplib2.StartSnmpPoll(*name, *snmppoll, *ptimeout)
		if err != nil {
			log.Fatalf("Error !%v", err)
		}
	} else {
		fmt.Print(parser.Usage(err))
		os.Exit(1)
	}
}
