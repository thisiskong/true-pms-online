package snmplib

import (
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"sync"

	"log"
	"net"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	_ "github.com/lib/pq" // Postgres database driver

	"github.com/gosnmp/gosnmp"
	"gopkg.in/yaml.v2"
)

// discid: disc.id (mandatory)
// discip: ipaddr (optional)
func loadDiscoveryRuleFromDB(setting *AppSetting, task *DiscoveryTask, discid int, discip string) error {
	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable"
	db, err := sql.Open("postgres", setting.DbConnection)
	if err != nil {
		return err
	}
	defer db.Close()

	var cond string
	var rows *sql.Rows
	if discid != -1 {
		sql := fmt.Sprintf(`select id, coalesce(ip_range, ''), local_addr, pollint, pollstatus, coalesce(network, ''), coalesce(topology, ''), coalesce(agent, 'default'), engine
													from disc
													where enabled=true and id=%d`, discid)

		log.Printf("sql = %s", sql)
		rows, err = db.Query(sql)

	} else {
		cond, err = buildQuery(setting, "id")
		if err != nil {
			log.Fatalf("Error! %v", err)
		}

		sql := fmt.Sprintf(`select id, coalesce(ip_range, ''), local_addr, pollint, pollstatus, coalesce(network, ''), coalesce(topology, ''), coalesce(agent, 'default'), engine
													from disc
													where enabled=true and %s`, cond)

		log.Printf("sql = %s", sql)
		rows, err = db.Query(sql)
	}
	if err != nil {
		return err
	}

	if rows == nil {
		return errors.New("invalid discovery parameter")
	}

	deviceCommunities, err := loadDeviceCommunityString(db)
	if err != nil {
		return err
	}

	disableIpAddrs, err := loadDiscoveryDisableIp(setting)
	if err != nil {
		return err
	}

	for rows.Next() {
		var disc Discovery
		err := rows.Scan(&disc.Id, &disc.IpRange, &disc.LocalAddr, &disc.PollInt, &disc.PollStatus, &disc.Network, &disc.Topology, &disc.Agent, &disc.Engine)
		if err != nil {
			log.Printf("Error! %v", err)
			return err
		}

		rows2, err := db.Query("select community from disc_comm where disc=$1", disc.Id)
		if err != nil {
			return err
		}
		var community string
		for rows2.Next() {
			rows2.Scan(&community)
			disc.Communities = append(disc.Communities, community)
		}
		ipaddrs := make([]string, 0)
		if discip != "" {
			ipaddrs = append(ipaddrs, discip)
		} else {
			ipaddrs = convert2IpList(disc.IpRange)
		}
		targets := makeSnmpTargets(task, &disc, deviceCommunities, ipaddrs, disableIpAddrs)
		disc.SnmpTargets = append(disc.SnmpTargets, *targets...)
		task.Discoveries = append(task.Discoveries, disc)
		log.Printf("disc=%s, network=%s, topology=%s, ip_range=%s has %d entries", disc.Id, disc.Network, disc.Topology, disc.IpRange, len(ipaddrs))
	}
	log.Printf("loadDiscoveryRule return %d entries", len(task.Discoveries))
	return nil
}

func loadIp2DiscoveryId(task *DiscoveryConfig) (*map[string]int, error) {
	ip2DiscId := make(map[string]int, 1000)

	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable"
	db, err := sql.Open("postgres", task.Setting.DbConnection)
	if err != nil {
		log.Printf("Error! %v", err)
		return &ip2DiscId, err
	}
	defer db.Close()

	rows, err := db.Query(`select ip_range, id from disc where enabled = true order by 1`)
	if err != nil {
		log.Printf("Error! %v", err)
		return &ip2DiscId, err
	}
	defer rows.Close()

	for rows.Next() {
		var ip_range string
		var id int
		rows.Scan(&ip_range, &id)
		for _, ipaddr := range convert2IpList(ip_range) {
			ip2DiscId[ipaddr] = id
		}
	}
	log.Printf("ip2DiscId return %d entries", len(ip2DiscId))
	return &ip2DiscId, nil
}

func LoadDiscoveryConfigByIp(filename string, discip string) (*DiscoveryConfig, error) {
	content, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}

	var task DiscoveryConfig
	err = yaml.Unmarshal(content, &task)
	if err != nil {
		return nil, err
	}
	ip2DiscId, err := loadIp2DiscoveryId(&task)
	if err != nil {
		return nil, err
	}
	discid, ok := (*ip2DiscId)[discip]
	if !ok {
		return nil, err
	}

	err = loadDiscoveryRuleFromDB(task.Setting, task.Discovery, discid, discip)
	if err != nil {
		return nil, err
	}
	return &task, nil
}

func LoadDiscoveryConfigById(filename string, discid int) (*DiscoveryConfig, error) {
	content, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}

	var task DiscoveryConfig
	err = yaml.Unmarshal(content, &task)
	if err != nil {
		return nil, err
	}

	err = loadDiscoveryRuleFromDB(task.Setting, task.Discovery, discid, "")
	if err != nil {
		return nil, err
	}
	return &task, nil
}

func LoadPollTrafficConfig(filename string) *PollTrafficConfig {
	content, err := os.ReadFile(filename)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	var task PollTrafficConfig
	err = yaml.Unmarshal(content, &task)
	if err != nil {
		log.Fatalf("Error! %v", err)
	}
	return &task
}

func LoadSnmpTarget(wg *sync.WaitGroup, task *PollTrafficConfig, pollint int) {
	defer wg.Done()

	jsonfile := fmt.Sprintf(".targets-%d.json", pollint)

	targets, err := loadTargetFromDb(task.Setting, pollint, task.PollTraffic)
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

	task.SnmpTargets = make([]SnmpTarget, len(targets))
	copy(task.SnmpTargets, targets)
}

func loadTargetFromDb(setting *AppSetting, pollint int, task *PollTrafficTask) ([]SnmpTarget, error) {
	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable"
	t := time.Now()
	db, err := sql.Open("postgres", setting.DbConnection)
	if err != nil {
		return nil, err
	}
	defer db.Close()

	cond, err := buildQuery(setting, "ip")
	if err != nil {
		log.Fatalf("Error! %v", err)
	}

	// mapper
	mapper, err := NewMapper(setting)
	if err != nil {
		log.Panic(err)
	}

	sql := fmt.Sprintf(`select
							id, ip, community, coalesce(name, ''), coalesce(agent, ''),
							coalesce(network, ''), coalesce(topology, ''), coalesce(sitename, ''), coalesce(vendor, ''), coalesce(model, '')
						from (
							select id, ip, community, name, coalesce(usr_pollstatus, sys_pollstatus) pollstatus, pollint, agent,
								network, topology, sitename, vendor, model,
								row_number() over (partition by ip order by lastseen desc) as rownum
								from device
								where coalesce(usr_pollstatus, sys_pollstatus) = 1
						) X
						where
							( %s )
							and rownum = 1
							and pollint = %d`, cond, pollint)

	log.Printf("%v", sql)
	rows, err := db.Query(sql)

	// hostname, _ := os.Hostname()
	// rows, err := db.Query(fmt.Sprintf(`
	// 									select
	// 										('x'|| md5(ip::text))::bit(32)::bigint %% %d cid,
	// 										id, ip, community, coalesce(name, ''), coalesce(agent, ''),
	// 										coalesce(network, ''), coalesce(topology, ''), coalesce(vendor, ''), coalesce(model, '')
	// 									from (
	// 										select id, ip, community, name, coalesce(usr_pollstatus, sys_pollstatus) pollstatus, pollint, agent,
	// 											network, topology, vendor, model,
	// 											row_number() over (partition by ip order by lastseen desc) as rownum
	// 											from device
	// 											where coalesce(usr_pollstatus, sys_pollstatus) = 1
	// 									) X
	// 									where
	// 										(
	// 											(
	// 												('x'|| md5(ip::text))::bit(32)::bigint %% %d = %d and agent is null
	// 											)
	// 											or agent = '%s'
	// 										)
	// 										and rownum = 1
	// 										and pollint = %d`, csize, csize, cid, hostname, pollint))
	if err != nil {
		return nil, err
	}
	targets := make([]SnmpTarget, 0)
	for rows.Next() {
		var id int64
		target := SnmpTarget{
			Port:          161,
			Version:       gosnmp.Version2c,
			Timeout:       task.SnmpOption.Timeout,
			Retries:       task.SnmpOption.Retries,
			MaxRepetition: task.SnmpOption.MaxRepetition,
			MaxReqOid:     task.SnmpOption.MaxReqOid,
			ExpTime:       task.SnmpOption.ExpTime,
			IcmpCount:     task.IcmpCount,
			IcmpInterval:  task.IcmpInterval,
			IcmpTimeout:   task.IcmpTimeout,
			Flags:         make([]string, 0),
			Interfaces:    make(map[string]*Intf),
		}
		err = rows.Scan(&id, &target.IP, &target.Community, &target.Device, &target.Agent, &target.Network, &target.Topology, &target.Sitename, &target.Vendor, &target.Model)
		if err != nil {
			return nil, err
		}

		// overwrite setting
		target = mapper.SnmpTarget(target)

		// query intfs
		rows2, err2 := db.Query(fmt.Sprintf(`select ifindex, ifalias, ifdescr, iftype, ifspeed, name, dstname, dstport, dstsite, dsttype
												from intf
												where
													coalesce(usr_pollstatus, sys_pollstatus) = 1
													and ifindex is not null and ifindex != ''
													and ifspeed > 0
													and device_id = %d`, id))
		if err2 != nil {
			return nil, err2
		}
		for rows2.Next() {
			var intf Intf
			rows2.Scan(&intf.Ifindex, &intf.Ifalias, &intf.Ifdescr, &intf.Iftype, &intf.Ifspeed,
				&intf.Name, &intf.Dstname, &intf.Dstport, &intf.Dstsite, &intf.Dsttype)
			target.Interfaces[intf.Ifindex] = &intf
		}
		targets = append(targets, target)
		// log.Printf("%v|%v|%v|%v|%v|%v|%v|%v|%v|%d", target.IP, target.Port, target.Community, target.Version, target.Timeout, target.Retries, target.MaxRepetition, target.ExpTimeout, target.Network, len(target.IfIndexes))
	}
	log.Printf("loadTargetFromDb return %d entries in %v", len(targets), time.Since(t))
	return targets, nil
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

func loadDiscoveryDisableIp(setting *AppSetting) (map[string]bool, error) {
	result := make(map[string]bool)
	t := time.Now()

	db, err := sql.Open("postgres", setting.DbConnection)
	if err != nil {
		return result, err
	}
	defer db.Close()

	rows, err := db.Query(`select ip from disc_exclude_ip`)
	if err != nil {
		return result, err
	}
	defer rows.Close()

	for rows.Next() {
		var ip string
		err := rows.Scan(&ip)
		if err != nil {
			return result, err
		}
		result[strings.TrimSpace(ip)] = true
	}
	log.Printf("loadDiscoveryDisableIp: return %d entries in %v", len(result), time.Since(t))
	return result, nil
}

func makeSnmpTargets(task *DiscoveryTask, disc *Discovery, deviceCommunities map[string]string, ipaddrs []string, disableIpAddrs map[string]bool) *[]SnmpTarget {
	snmpTargets := make([]SnmpTarget, 0, len(ipaddrs))
	for _, ipaddr := range ipaddrs {
		// check if ipaddr is disabled
		_, ok := disableIpAddrs[ipaddr]
		if !ok {
			community := deviceCommunities[ipaddr]
			target := SnmpTarget{
				IP:            ipaddr,
				Port:          161,
				Device:        ipaddr,
				Community:     community,
				Network:       disc.Network,
				Topology:      disc.Topology,
				Agent:         disc.Agent,
				PollStatus:    disc.PollStatus,
				Version:       gosnmp.Version2c,
				Timeout:       task.SnmpOption.Timeout,
				Retries:       task.SnmpOption.Retries,
				MaxRepetition: task.SnmpOption.MaxRepetition,
				MaxReqOid:     task.SnmpOption.MaxReqOid,
				ExpTime:       task.SnmpOption.ExpTime,
				IcmpCount:     task.IcmpCount,
				IcmpInterval:  task.IcmpInterval,
				IcmpTimeout:   task.IcmpTimeout,
				Flags:         make([]string, 0),
			}
			snmpTargets = append(snmpTargets, target)
		}
	}
	return &snmpTargets
}

func convertIpSubnet2IpList(ip_or_subnet string, inc_broadcast bool) []string {
	// input:
	// 	10.1.2.3
	// 	10.1.2.0/16
	var ipaddrs []string
	if net.ParseIP(ip_or_subnet) != nil {
		// ip address
		ipaddrs = append(ipaddrs, ip_or_subnet)
	} else {
		tokens := strings.Split(ip_or_subnet, "/")
		if len(tokens) == 1 {
			ipaddrs = append(ipaddrs, ip_or_subnet)

		} else if len(tokens) == 2 {
			// convert string to IPNet struct
			_, ipv4Net, err := net.ParseCIDR(ip_or_subnet)
			if err != nil {
				log.Printf("Error! invalid subnet %s", ip_or_subnet)
			} else {
				// convert IPNet struct mask and address to uint32
				// network is BigEndian
				mask := binary.BigEndian.Uint32(ipv4Net.Mask)
				start := binary.BigEndian.Uint32(ipv4Net.IP)

				// find the final address
				finish := (start & mask) | (mask ^ 0xffffffff)

				// loop through addresses as uint32
				if inc_broadcast {
					for i := start; i <= finish; i++ {
						// convert back to net.IP
						ip := make(net.IP, 4)
						binary.BigEndian.PutUint32(ip, i)
						ipaddrs = append(ipaddrs, ip.String())
					}
				} else {
					for i := start; i < finish; i++ {
						// convert back to net.IP
						ip := make(net.IP, 4)
						binary.BigEndian.PutUint32(ip, i)
						ipaddrs = append(ipaddrs, ip.String())
					}
				}
			}
		}
	}
	return ipaddrs
}

func convertIpSubnetPattern2IpSubnetList(str string) []string {
	//	10.1.2.0/16
	//	10.1.[1,2,3].0/16
	//	10.1.[1-10].0/16
	//	10.1.1.[1-3]
	ip_subnet_list := make([]string, 0)
	tokens := strings.Split(str, "/")
	if len(tokens) == 1 {
		// Range
		tokens = strings.Split(tokens[0], ".")
		if len(tokens) == 4 {
			// log.Printf("%s|%s|%s|%s", tokens[0], tokens[1], tokens[2], tokens[3])
			for _, val_0 := range convertToNumbers(tokens[0]) {
				for _, val_1 := range convertToNumbers(tokens[1]) {
					for _, val_2 := range convertToNumbers(tokens[2]) {
						for _, val_3 := range convertToNumbers(tokens[3]) {
							ip := fmt.Sprintf("%v.%v.%v.%v", val_0, val_1, val_2, val_3)
							ip_subnet_list = append(ip_subnet_list, ip)
						}
					}
				}
			}
		}
	} else if len(tokens) == 2 {
		// Subnet
		ip_pattern := tokens[0]
		mask := tokens[1]
		tokens = strings.Split(ip_pattern, ".")
		if len(tokens) == 4 {
			for _, val_0 := range convertToNumbers(tokens[0]) {
				for _, val_1 := range convertToNumbers(tokens[1]) {
					for _, val_2 := range convertToNumbers(tokens[2]) {
						for _, val_3 := range convertToNumbers(tokens[3]) {
							ip_subnet := fmt.Sprintf("%v.%v.%v.%v/%v", val_0, val_1, val_2, val_3, mask)
							ip_subnet_list = append(ip_subnet_list, ip_subnet)
						}
					}
				}
			}
		}
	}
	return ip_subnet_list
}

func convertToNumbers(str string) []string {
	// 10
	// [1,2,3]
	// [1,2,3,10-20]
	// [1-10]
	str = strings.ReplaceAll(str, " ", "")
	entries := make([]string, 0)
	p1 := regexp.MustCompile(`^\d{1,3}$`)
	p2 := regexp.MustCompile(`^\d{1,3}-\d{1,3}$`)
	m := p1.MatchString(str)
	if m {
		entries = append(entries, str)
	} else if strings.HasPrefix(str, "[") && strings.HasSuffix(str, "]") {
		for _, val := range strings.Split(str[1:len(str)-1], ",") {
			m := p1.MatchString(val)
			if m {
				entries = append(entries, val)
			} else {
				m := p2.MatchString(val)
				if m {
					tokens := strings.Split(val, "-")
					if len(tokens) == 2 {
						first, _ := strconv.Atoi(tokens[0])
						last, _ := strconv.Atoi(tokens[1])
						for i := first; i <= last; i++ {
							entries = append(entries, fmt.Sprintf("%d", i))
						}
					}
				}
			}
		}
	}
	// log.Printf("convertToNumbers: %v = %v", str, entries)
	return entries
}

func convert2IpList(iprange string) []string {
	ipaddrs := make([]string, 0)
	if strings.Contains(iprange, "/") {
		// log.Printf("convert2IpList: %v [Subnet]", iprange)
		for _, subnet := range convertIpSubnetPattern2IpSubnetList(iprange) {
			// log.Printf("  + %v", subnet)
			ipaddrs = append(ipaddrs, convertIpSubnet2IpList(subnet, false)...)
		}
	} else {
		// log.Printf("convert2IpList: %v [Range]", iprange)
		ipaddrs = append(ipaddrs, convertIpSubnetPattern2IpSubnetList(iprange)...)
	}
	// log.Printf("convert2IpList: %v return %d entries", iprange, len(ipaddrs))
	return ipaddrs
}

func loadDeviceCommunityString(db *sql.DB) (map[string]string, error) {
	rows, err := db.Query(`select ip, community from (
														select id,
																	ip,
																	community,
																	row_number() over (partition by ip order by lastseen desc) as rownum
															from device
													) x where rownum = 1`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	deviceCommunities := make(map[string]string)
	for rows.Next() {
		var ip string
		var community string
		err = rows.Scan(&ip, &community)
		if err != nil {
			return nil, err
		}
		deviceCommunities[ip] = community
	}
	return deviceCommunities, nil
}

// func isMyDiscovery(setting *AppSetting, disc *Discovery) bool {
// 	hostname, _ := os.Hostname()
// 	for _, pagent := range setting.PollAgent {
// 		if disc.Agent == pagent.Name {
// 			for idx, node := range pagent.Nodes {
// 				if hostname == node {
// 					size := int64(len(pagent.Nodes))
// 					cid := disc.Hash % size
// 					if int64(idx) == cid {
// 						// log.Printf("isMyTask: %v, hash=%d, size=%d, cid=%d [True]", disc.Agent, disc.Hash, size, cid)
// 						return true
// 					}
// 				}
// 			}
// 		}
// 	}
// 	return false
// }

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

type AgentInfo struct {
	name  string
	nodes []string
	cid   int
}

func Test() {
	// for _, ip := range convertIpSubnet2IpList("10.1.1.0/28", false) {
	// 	log.Printf("%v", ip)
	// }
	// convert2IpList("10.1.1.0/28")
	// convert2IpList("10.1.[1,2].3/28")
	// convert2IpList("10.1.[1,2].[4,5-7]/28")
	// convert2IpList("10.1.[1,2].[4,5-7]/30")
	// convert2IpList("10.167.0.0/16")
	// convertIpSubnetPattern2IpSubnetList("10.1.[1-3].3/28")
	// convertIpSubnetPattern2IpSubnetList("10.[1,2,5-7].[1,2].0/30")
	// convertIpPattern2IpList("10.1.1.2")
	// convertIpPattern2IpList(ip_pattern)("10.1.[1,3].[0-10]")
	// for _, target := range *makeSnmpTargetFromIpSubnet("10.1.[1,2].3/28", "public", 0, 0) {
	// 	log.Printf("%v", target.IP)
	// }
}
