package snmplib

import (
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"strings"

	"github.com/robertkrimen/otto"
)

type Mapper struct {
	// vm *otto.Otto
	script string
	db     *sql.DB
}

func NewMapper(setting *AppSetting) (*Mapper, error) {

	db, err := sql.Open("postgres", setting.DbConnection)
	if err != nil {
		log.Panic(err)
	}

	var content string
	err = db.QueryRow("select content from scriptobj where id='mapping.js'").Scan(&content)
	if err != nil {
		return nil, err
	}
	// // javascript
	// vm := otto.New()

	// // validate script
	// _, err = vm.Run(content)
	// if err != nil {
	// 	return nil, err
	// }
	// return &Mapper{vm: vm, db: db}, nil
	return &Mapper{script: content, db: db}, nil
}

func (m *Mapper) NewVm() *otto.Otto {
	vm := otto.New()
	_, err := vm.Run(m.script)
	if err != nil {
		panic(err)
	}
	return vm
}

func (m *Mapper) MapDevice(deviceInst *Device) error {
	attrs := make(map[string]interface{})
	vm := m.NewVm()
	ret, err := vm.Call("mapDevice", nil, deviceInst)
	if err != nil {
		log.Printf("Error! mapping [mapDevice] %v", err)
		return err
	}
	maps, _ := ret.Export()
	switch v := maps.(type) {
	case map[string]interface{}:
		for key, val := range v {
			if val != nil {
				switch x := val.(type) {
				case string:
					attrs[key] = x
				case int64:
					attrs[key] = x
				}
			} else {
				attrs[key] = ""
			}
		}
		vendor, _ := attrs["vendor"].(string)
		model, _ := attrs["model"].(string)
		swversion, _ := attrs["swversion"].(string)
		sitename, _ := attrs["sitename"].(string)
		province, _ := attrs["province"].(string)
		olttype, _ := attrs["olttype"].(string)
		pollstatus, _ := attrs["pollStatus"].(int64)

		deviceInst.Vendor = vendor
		deviceInst.Model = model
		deviceInst.SwVersion = swversion
		deviceInst.Sitename = sitename
		deviceInst.Province = province
		deviceInst.OltType = olttype
		deviceInst.PollStatus = pollstatus
		return nil

	default:
		err = errors.New("invalid type")
		log.Printf("Error! invalid return type: %v", err)
		return err
	}
}

func (m *Mapper) MapIntfs(deviceInst *Device) error {
	vm := m.NewVm()
	ret, err := vm.Call("mapIntfs", nil, deviceInst)
	if err != nil {
		log.Printf("Error! mapping [MapIntfs] %v", err)
		return err
	}
	maps, _ := ret.Export()
	switch v := maps.(type) {
	case map[string]interface{}:
		intfs := v["intfs"]
		switch w := intfs.(type) {
		case []map[string]interface{}:
			for i, intf := range w {
				ifname, _ := intf["ifname"].(string)
				name, _ := intf["name"].(string)
				dstsite, _ := intf["dstsite"].(string)
				dsttype, _ := intf["dsttype"].(string)
				remdstsite, _ := intf["remdstsite"].(string)
				mediatype, _ := intf["mediatype"].(string)
				pollStatus, _ := intf["pollStatus"].(int64)
				ponport, _ := intf["ponport"].(string)
				altname, _ := intf["altname"].(string)
				save, _ := intf["save"].(bool)

				dstsite2, dsttype2 := m.GetAltDstSite(dstsite, dsttype)

				// ifspeed input type uint64, however, if discovery script set value using direct number assignment, it will change type to int64
				// support for both int64 and uint64 type of ifspeed
				var ifspeed uint64
				val := intf["ifspeed"]
				switch k := val.(type) {
				case int64:
					ifspeed = uint64(k)
				case uint64:
					ifspeed = k
				}

				deviceInst.Interfaces[i].IfName = ifname
				deviceInst.Interfaces[i].Name = name
				deviceInst.Interfaces[i].DstSite = dstsite
				deviceInst.Interfaces[i].DstType = dsttype
				deviceInst.Interfaces[i].RemDstSite = remdstsite
				deviceInst.Interfaces[i].MediaType = mediatype
				deviceInst.Interfaces[i].PollStatus = pollStatus
				deviceInst.Interfaces[i].PonPort = ponport
				deviceInst.Interfaces[i].AltName = altname
				deviceInst.Interfaces[i].IfSpeed = ifspeed
				deviceInst.Interfaces[i].DstSite2 = dstsite2
				deviceInst.Interfaces[i].DstType2 = dsttype2
				deviceInst.Interfaces[i].Save = save
			}
		}
		return nil
	default:
		err = errors.New("invalid type")
		log.Printf("Error! invalid return type: %v", err)
		return err
	}
}

func (m *Mapper) MapBoards(deviceInst *Device, snmpTables map[string]*SnmpTable) error {
	vm := m.NewVm()
	ret, err := vm.Call("mapBoards", nil, deviceInst, snmpTables)
	if err != nil {
		log.Printf("Error! mapping [MapBoards] %v", err)
		return err
	}
	maps, _ := ret.Export()
	if debug {
		s, _ := json.MarshalIndent(maps, "", " ")
		log.Printf("MapBoards = %s", s)
	}
	switch v := maps.(type) {
	case map[string]interface{}:
		boards := v["boards"]
		switch w := boards.(type) {
		case []map[string]interface{}:
			for _, board := range w {
				id, _ := board["id"].(string)
				boardName, _ := board["boardName"].(string)
				boardType, _ := board["boardType"].(string)
				boardRole, _ := board["boardRole"].(string)
				operStatus, _ := board["operStatus"].(string)

				board := Board{
					Id:         id,
					BoardName:  boardName,
					BoardType:  boardType,
					BoardRole:  boardRole,
					OperStatus: operStatus,
				}
				deviceInst.Boards = append(deviceInst.Boards, &board)
			}
		}
		return nil
	default:
		err = errors.New("invalid type")
		log.Printf("Error! invalid return type: %v", err)
		return err
	}
}

func (m *Mapper) SnmpTarget(target SnmpTarget) SnmpTarget {
	vm := m.NewVm()
	ret, err := vm.Call("snmp_target", nil, target)
	if err != nil {
		log.Printf("Error! %v", err)
		return target
	}

	maps, _ := ret.Export()
	switch v := maps.(type) {
	case map[string]interface{}:
		for key, val := range v {
			if key == "icmpCount" {
				target.IcmpCount = int(val.(int64))
			} else if key == "icmpInterval" {
				target.IcmpInterval = int(val.(int64))
			} else if key == "icmpTimeout" {
				target.IcmpTimeout = int(val.(int64))
			} else if key == "timeout" {
				target.Timeout = uint16(val.(int64))
			} else if key == "retries" {
				target.Retries = int(val.(int64))
			} else if key == "maxRepetition" {
				target.MaxRepetition = uint32(val.(int64))
			} else if key == "expTime" {
				target.ExpTime = val.(bool)
			} else if key == "maxReqOid" {
				target.MaxReqOid = int(val.(int64))
			} else if key == "flags" {
				target.Flags = append(target.Flags, strings.Split(val.(string), ",")...)
			}
		}
	}
	return target
}

func (m *Mapper) GetAltDstSite(dstsite string, dsttype string) (string, string) {
	dstsite2 := dstsite
	dsttype2 := dsttype
	if dstsite != "" {
		err := m.db.QueryRow(fmt.Sprintf(`select name, topology from
							(select name, topology, ip, row_number() over (partition by ip order by lastseen desc) as rownum
								from device
								where coalesce(usr_pollstatus, sys_pollstatus) = 1 and (ip = '%s' or name = '%s')
							) d
							where rownum = 1`, dstsite, dstsite)).Scan(&dstsite2, &dsttype2)
		if err != nil {
			dstsite2 = dstsite
			dsttype2 = dsttype
		}
		log.Printf("GetAltDstSite: %s:%s => %s:%s", dstsite, dsttype, dstsite2, dsttype2)
	}
	return dstsite2, dsttype2
}

func (m *Mapper) SetProvince(deviceInst *Device, provinceCode *map[string]string) {
	code := deviceInst.SysName
	if (len(deviceInst.SysName)) >= 5 {
		code = deviceInst.SysName[:5]
	}
	deviceInst.Province = (*provinceCode)[code]
}

func (m *Mapper) SetDiscoveryFields(deviceInst *Device, disc *Discovery) {
	deviceInst.DiscoveryPollInt = 0
	if disc != nil {
		deviceInst.Engine = disc.Engine
		deviceInst.Agent = disc.Agent
		deviceInst.DiscoveryId = disc.Id
		if disc.PollInt != nil {
			deviceInst.DiscoveryPollInt = *disc.PollInt
		}
		if disc.PollStatus {
			deviceInst.PollStatus = 1
		}
	}
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
}
