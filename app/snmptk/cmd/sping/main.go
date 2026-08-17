package main

import (
	"encoding/csv"
	"encoding/hex"
	"errors"
	"fmt"
	"log"
	"os"
	"sync"
	"time"
	"unicode"

	"true-pms-online/internal/snmplib"
	"go.uber.org/ratelimit"

	"github.com/akamensky/argparse"
	"github.com/go-ping/ping"
	"github.com/gosnmp/gosnmp"
	"github.com/hako/durafmt"
)

type Target struct {
	host             string
	snmp_port        uint16
	snmp_communities []string
	snmp_timeout     time.Duration
	snmp_retries     int
	icmp_timeout     time.Duration
	icmp_interval    time.Duration
	icmp_count       int
}

type TestResult struct {
	Target     Target
	IcmpResult string
	Community  string
	SnmpErr    string
	SysName    string
}

func TestResultProcessor(wg *sync.WaitGroup, size int, outfile *string, tasksDone chan TestResult) {
	defer wg.Done()

	var fout *os.File
	var err error
	if outfile != nil {
		fout, err = os.OpenFile(*outfile, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0644)
		if err != nil {
			log.Fatalf("Error! %v", err)
		}
		defer fout.Close()
	}

	for i := 0; i < size; i++ {
		result, ok := <-tasksDone
		if !ok {
			// channel was closed
			log.Fatal("Error! channel is closed")
		}

		log.Printf("sping|%v|%v|%v|%v", result.Target.host, result.IcmpResult, result.Community, result.SysName)
		if fout != nil {
			line := fmt.Sprintf("%v|%v|%v|%v\n", result.Target.host, result.IcmpResult, result.Community, result.SysName)
			fout.WriteString(line)
		}
	}
}

func IcmpPingIp(ip string, wg *sync.WaitGroup) {
	defer wg.Done()
	t := time.Now()
	pinger, err := ping.NewPinger(ip)
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}
	pinger.SetPrivileged(true)
	pinger.Count = 1
	pinger.Interval = time.Duration(200) * time.Millisecond
	pinger.Timeout = time.Duration(1) * time.Second

	err = pinger.Run() // Blocks until finished.
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}

	stats := pinger.Statistics() // get send/receive/duplicate/rtt stats
	log.Printf("sent: %d, recv: %d, %%loss: %f, total time: %v", stats.PacketsSent, stats.PacketsRecv, stats.PacketLoss, time.Since(t))
}

func IcmpPingIpBurst(ip string, burst_cnt int) {
	t := time.Now()
	var wg sync.WaitGroup
	for i := 0; i < burst_cnt; i++ {
		wg.Add(1)
		go IcmpPingIp(ip, &wg)
	}
	wg.Wait()
	log.Printf("Total time: %v", time.Since(t))
}

func IcmpPingSnmpGet(rl ratelimit.Limiter, wg *sync.WaitGroup, target Target, tasksDone chan TestResult) {
	defer wg.Done()

	// acquire token, block if full
	rl.Take()

	ret := TestResult{Target: target}

	pinger, err := ping.NewPinger(target.host)
	if err != nil {
		log.Printf("icmp: %v|%v", target.host, err.Error())
		ret.IcmpResult = fmt.Sprintf("Icmp Error: %v", err.Error())
		tasksDone <- ret
		return
	}
	pinger.SetPrivileged(true)
	pinger.Count = target.icmp_count
	pinger.Timeout = target.icmp_timeout
	pinger.Interval = target.icmp_interval

	// log.Printf("IcmpPing: %s, %s", target.IP, "Sent")
	err = pinger.Run() // Blocks until finished.
	if err != nil {
		log.Printf("icmp: %v|%v", target.host, err.Error())
		ret.IcmpResult = fmt.Sprintf("Icmp Error: %v", err.Error())
		tasksDone <- ret
		return
	}

	stats := pinger.Statistics() // get send/receive/duplicate/rtt stats
	var icmp_result string
	if stats.PacketsSent > 0 && stats.PacketsRecv > 0 && stats.PacketsSent == stats.PacketsRecv {
		icmp_result = "Ok"
	} else if stats.PacketsSent > 0 && stats.PacketsRecv > 0 && stats.PacketsRecv < stats.PacketsSent {
		icmp_result = "Intermittent"
	} else {
		icmp_result = "Error"
	}
	ret.IcmpResult = icmp_result
	log.Printf("icmp: %v|%v|sent=%d, recv=%d, dup=%d, %%loss=%.0f",
		target.host, icmp_result, stats.PacketsSent, stats.PacketsRecv, stats.PacketsRecvDuplicates, stats.PacketLoss)

	for _, community := range target.snmp_communities {
		sysname, err := SnmpGetSysName(target, community)
		if err == nil {
			ret.Community = community
			ret.SysName = sysname
			break
		}
	}
	tasksDone <- ret
}

func SnmpGetSysName(target Target, community string) (string, error) {
	oids := []string{"1.3.6.1.2.1.1.5.0"}

	// build our own GoSNMP struct, rather than using g.Default
	params := &gosnmp.GoSNMP{
		Target:             target.host,
		Port:               target.snmp_port,
		Version:            gosnmp.Version2c,
		Community:          community,
		Timeout:            target.snmp_timeout,
		ExponentialTimeout: false,
		Retries:            target.snmp_retries,
		// Logger:             logger,
	}

	err := params.Connect()
	if err != nil {
		log.Printf("snmpget: %v|%v|%v", target.host, community, err)
		return "", err
	}
	defer params.Conn.Close()

	// log.Printf("snmpget: %v|%v|%v", target.host, oids, target.snmp_communities)
	snmpResult, err := params.Get(oids)
	if err != nil {
		// error, try next community string
		log.Printf("snmpget: %v|%v|%v", target.host, community, err)
		return "", err
	}

	// successful
	for i := 0; i < len(snmpResult.Variables); i++ {
		snmpVar := snmpResult.Variables[i]
		if snmpVar.Name == ".1.3.6.1.2.1.1.5.0" {
			sysname := ToString(snmpVar)
			log.Printf("snmpget: %v|%v|%v", target.host, community, sysname)
			return sysname, nil
		}
	}
	log.Printf("snmpget: %v|%v|%v", target.host, community, "no-return-value")
	return "", errors.New("no return value")
}

func process(infile *string, outfile *string, rate *int, icmp_timeout *int, icmp_count *int, icmp_interval *int,
	snmp_communities *[]string, snmp_timeout *int, snmp_retries *int) {

	fin, err := os.Open(*infile)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	defer fin.Close()

	// read csv values using csv.Reader
	csvReader := csv.NewReader(fin)
	csvReader.Comma = '|'
	lines, err := csvReader.ReadAll()
	if err != nil {
		log.Fatalf("Error! %v", err)
	}

	var wg sync.WaitGroup
	tasksDone := make(chan TestResult)
	rlimit := ratelimit.New(*rate)

	targets := make([]Target, 0, 100)
	for _, line := range lines {
		target := Target{
			host:             line[0],
			snmp_port:        161,
			snmp_communities: *snmp_communities,
			icmp_timeout:     time.Duration(*icmp_timeout) * time.Millisecond,
			icmp_count:       *icmp_count,
			icmp_interval:    time.Duration(*icmp_interval) * time.Millisecond,
			snmp_timeout:     time.Duration(*snmp_timeout) * time.Millisecond,
			snmp_retries:     *snmp_retries,
		}
		targets = append(targets, target)
	}

	wg.Add(1)
	go TestResultProcessor(&wg, len(targets), outfile, tasksDone)
	for _, target := range targets {
		wg.Add(1)
		go IcmpPingSnmpGet(rlimit, &wg, target, tasksDone)
	}

	log.Printf("working...")
	wg.Wait()
	log.Printf("completed")
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

func isASCII(value string) bool {
	for _, c := range value {
		if c > unicode.MaxASCII {
			return false
		}
	}
	return true
}

func main() {
	// Create new parser object
	parser := argparse.NewParser("Snmp & Ping", "Snmp & Ping Toolkit")
	infile := parser.String("i", "input", &argparse.Options{Required: false, Help: "ipaddr file"})
	outfile := parser.String("o", "output", &argparse.Options{Required: false, Help: "output file"})
	ip := parser.String("", "ip", &argparse.Options{Required: false, Help: "IP address"})
	burst := parser.Int("", "burst", &argparse.Options{Required: false, Default: 1, Help: "Icmp Burst"})
	rate := parser.Int("R", "rate", &argparse.Options{Required: false, Default: 20, Help: "rate limit (request per sec)"})
	icmp_timeout := parser.Int("T", "icmp-timeout", &argparse.Options{Required: false, Default: 200, Help: "icmp timeout (millisecond)"})
	icmp_count := parser.Int("n", "icmp-count", &argparse.Options{Required: false, Default: 1, Help: "icmp packet count"})
	icmp_interval := parser.Int("", "icmp-interval", &argparse.Options{Required: false, Default: 100, Help: "interval between each icmp echo (millisecond)"})
	snmp_comms := parser.List("c", "community", &argparse.Options{Required: false, Default: []string{}, Help: "snmp community"})
	snmp_timeout := parser.Int("t", "snmp-timeout", &argparse.Options{Required: false, Default: 3000, Help: "snmp timeout (millisecond)"})
	snmp_retries := parser.Int("r", "snmp-retries", &argparse.Options{Required: false, Default: 0, Help: "snmp retries"})
	debug := parser.Flag("", "debug", &argparse.Options{Required: false, Default: false, Help: "Turn-on snmp debug log"})

	// log to stdout
	log.SetOutput(os.Stdout)

	// Parse input
	err := parser.Parse(os.Args)
	if err != nil {
		// In case of error print error and print usage
		// This can also be done by passing -h or --help flags
		fmt.Print(parser.Usage(err))
		os.Exit(1)
	}

	if *debug {
		snmplib.SnmpDebugEnable()
	}

	if *infile != "" {
		process(infile, outfile, rate, icmp_timeout, icmp_count, icmp_interval, snmp_comms, snmp_timeout, snmp_retries)

	} else if *ip != "" {
		IcmpPingIpBurst(*ip, *burst)
	} else {
		fmt.Print(parser.Usage(err))
		os.Exit(1)
	}
}
