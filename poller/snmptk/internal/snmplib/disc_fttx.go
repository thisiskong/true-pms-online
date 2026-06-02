package snmplib

import (
	"encoding/json"
	"fmt"
	"log"

	"true-pms-online/internal/snmplib2"
)

func set_fttx_intf_moduleclass(task *DiscoveryConfig, target *SnmpTarget, deviceInst *Device) {
	// Uplink moduleclass & vendorPn

	tbname := fmt.Sprintf("intf_moduleclass_FTTx_%s", deviceInst.Vendor)
	log.Printf("set_fttx_intf_moduleclass: %s", tbname)

	for name, tb := range task.Discovery.ExtSnmpTables {
		if name == tbname {
			tbResult, err := GetTable(task.Setting, target, &tb, true)
			if err != nil {
				log.Printf("%s: %s, %s %s error: %v", tb.Name, target.IP, target.Community, tb.Name, err)
				return
			}

			log.Printf("%s: %s, %s %s return %d entries", tb.Name, target.IP, target.Community, tb.Name, len(tbResult.Entries))
			if debug {
				s, _ := json.MarshalIndent(tbResult, "", " ")
				log.Printf("%s = %s", tbname, s)
			}

			if deviceInst.Vendor == "Fiberhome" {
				for _, entry := range tbResult.Entries {
					ifName := entry.GetValue("ifName")
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort == "" && intf.IfName == ifName {
							intf.VendorPn = entry.GetValue("vendorPn")
							moduleclass := entry.GetValue("moduleclass")
							if moduleclass != "unknown" {
								intf.ModuleClass = moduleclass
							}
							break
						}
					}
				}

			} else if deviceInst.Vendor == "ZTE" || deviceInst.Vendor == "Huawei" || deviceInst.Vendor == "Dasan" {
				for _, entry := range tbResult.Entries {
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort == "" && entry.Index == intf.IfIndex {
							intf.VendorPn = entry.GetValue("vendorPn")
							intf.ModuleClass = entry.GetValue("moduleclass")
							break
						}
					}
				}

			} else if deviceInst.Vendor == "Nokia" {
				for _, entry := range tbResult.Entries {
					ifIndex := ""
					if entry.Index == "257" {
						ifIndex = "131072"
					} else if entry.Index == "258" {
						ifIndex = "262144"
					}
					if ifIndex != "" {
						for _, intf := range deviceInst.Interfaces {
							if intf.PonPort == "" && ifIndex == intf.IfIndex {
								intf.VendorPn = entry.GetValue("vendorPn")
								intf.ModuleClass = entry.GetValue("moduleclass")
								break
							}
						}
					}
				}
			}
		}
	}
}

func set_fttx_intf_dstsite(task *DiscoveryConfig, target *SnmpTarget, deviceInst *Device) {
	// Uplink dstsite (For Nokia only)

	tbname := fmt.Sprintf("intf_dstsite_FTTx_%s", deviceInst.Vendor)
	log.Printf("set_fttx_intf_dstsite: %s", tbname)

	for name, tb := range task.Discovery.ExtSnmpTables {
		if name == tbname {
			tbResult, err := GetTable(task.Setting, target, &tb, true)
			if err != nil {
				log.Printf("%s: %s, %s %s error: %v", tb.Name, target.IP, target.Community, tb.Name, err)
				return
			}

			log.Printf("%s: %s, %s %s return %d entries", tb.Name, target.IP, target.Community, tb.Name, len(tbResult.Entries))
			if debug {
				s, _ := json.MarshalIndent(tbResult, "", " ")
				log.Printf("%s = %s", tbname, s)
			}

			if deviceInst.Vendor == "Nokia" {
				for _, entry := range tbResult.Entries {
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort == "" && entry.Index == intf.IfIndex {
							log.Printf("NokiaDstSite: %s|%s", entry.Index, entry.GetValue("nokiaDstSite"))
							intf.NokiaDstSite = entry.GetValue("nokiaDstSite")
							break
						}
					}
				}
			}
		}
	}
}

func set_fttx_ponport_moduleclass(task *DiscoveryConfig, target *SnmpTarget, deviceInst *Device) {
	// PonPort moduleclass & vendorPn

	tbname := fmt.Sprintf("ponport_moduleclass_FTTx_%s", deviceInst.Vendor)
	log.Printf("set_fttx_ponport_moduleclass: %s", tbname)

	for name, tb := range task.Discovery.ExtSnmpTables {
		if name == tbname {
			tbResult, err := GetTable(task.Setting, target, &tb, true)
			if err != nil {
				log.Printf("%s: %s, %s %s error: %v", tb.Name, target.IP, target.Community, tb.Name, err)
				return
			}

			log.Printf("%s: %s, %s %s return %d entries", tb.Name, target.IP, target.Community, tb.Name, len(tbResult.Entries))
			if debug {
				s, _ := json.MarshalIndent(tbResult, "", " ")
				log.Printf("%s = %s", tbname, s)
			}

			if deviceInst.Vendor == "Fiberhome" {
				for _, entry := range tbResult.Entries {
					ifName := entry.GetValue("ifName")
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort != "" && intf.IfName == ifName {
							intf.VendorPn = entry.GetValue("vendorPn")
							moduleclass := entry.GetValue("moduleclass")
							if moduleclass != "unknown" {
								intf.ModuleClass = moduleclass
							}
							break
						}
					}
				}

			} else if deviceInst.Vendor == "ZTE" {
				for _, entry := range tbResult.Entries {
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort != "" && entry.Index == intf.IfIndex {
							intf.VendorPn = entry.GetValue("vendorPn")
							intf.ModuleClass = entry.GetValue("moduleclass")
							log.Printf("ponport_moduleclass=%v|%v", intf.IfIndex, intf.ModuleClass)
							break
						}
					}
				}

			} else if deviceInst.Vendor == "Huawei" {
				for _, entry := range tbResult.Entries {
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort != "" && entry.Index == intf.IfIndex {
							intf.VendorPn = entry.GetValue("vendorPn")
							intf.ModuleClass = fmt.Sprintf("%s-%s", entry.GetValueDefault("moduletype", "None"), entry.GetValue("moduleclass"))
							break
						}
					}
				}

			} else if deviceInst.Vendor == "Dasan" {
				for _, entry := range tbResult.Entries {
					for _, intf := range deviceInst.Interfaces {
						if intf.PonPort != "" && entry.Index == intf.IfIndex {
							intf.VendorPn = entry.GetValue("vendorPn")
							intf.ModuleClass = entry.GetValue("moduleclass")
							break
						}
					}
				}

			} else if deviceInst.Vendor == "Nokia" {
				for _, intf := range deviceInst.Interfaces {
					if intf.PonPort != "" {
						oltPonId := snmplib2.GetOltPonIdForNokia(intf.IfIndex)
						for _, entry := range tbResult.Entries {
							if entry.Index == oltPonId {
								intf.VendorPn = entry.GetValue("vendorPn")
								intf.ModuleClass = entry.GetValue("moduleclass")
								break
							}
						}
					}
				}
			}
		}
	}
}

// func set_fttx_ponport_cardtype(task *DiscoveryConfig, target *SnmpTarget, deviceInst *Device) {
// 	// PonPort cardtype
// 	tbname := fmt.Sprintf("ponport_cardtype_FTTx_%s", deviceInst.Vendor)
// 	log.Printf("set_fttx_ponport_cardtype: %s", tbname)
// 	for name, tb := range task.Discovery.ExtSnmpTables {
// 		if name == tbname {
// 			tbResult, err := GetTable(task.Setting, target, &tb, true)
// 			if err != nil {
// 				log.Printf("%s: %s, %s %s error: %v", tb.Name, target.IP, target.Community, tb.Name, err)
// 				return
// 			}
// 			log.Printf("%s: %s, %s %s return %d entries", tb.Name, target.IP, target.Community, tb.Name, len(tbResult.Entries))
// 			if debug {
// 				s, _ := json.MarshalIndent(tbResult, "", " ")
// 				log.Printf("%s = %s", tbname, s)
// 			}
// 			if deviceInst.Vendor == "ZTE" {
// 				cardTypes := make(map[string]string)
// 				for _, entry := range tbResult.Entries {
// 					// Index   = <rack>.<shelf>.<slot>
// 					// PonPort = <rack>.<shelf>.<slot>.<port>
// 					rack_shelf_slot := strings.ReplaceAll(entry.Index, ".", "-")
// 					cardTypes[rack_shelf_slot] = entry.GetValue("cardtype")
// 				}
// 				regex, _ := regexp.Compile(`^(\d+-\d+-\d+)-\d+$`)
// 				for _, intf := range deviceInst.Interfaces {
// 					matches := regex.FindStringSubmatch(intf.PonPort)
// 					if len(matches) >= 2 {
// 						intf.CardType = cardTypes[matches[1]]
// 						// log.Printf("cardType: %s = %s", matches[1], intf.CardType)
// 					}
// 				}
// 			}
// 		}
// 	}
// }

func set_fttx_board(task *DiscoveryConfig, target *SnmpTarget, deviceInst *Device, mapper *Mapper) {

	tbname := fmt.Sprintf("board_FTTx_%s", deviceInst.Vendor)
	log.Printf("set_fttx_board: %s", tbname)

	snmpTables := make(map[string]*SnmpTable)
	for name, tb := range task.Discovery.ExtSnmpTables {
		if name == tbname {
			tbResult, err := GetTable(task.Setting, target, &tb, true)
			if err != nil {
				log.Printf("%s: %s, %s %s error: %v", tb.Name, target.IP, target.Community, tb.Name, err)
				return
			}

			log.Printf("%s: %s, %s %s return %d entries", tb.Name, target.IP, target.Community, tb.Name, len(tbResult.Entries))
			if debug {
				s, _ := json.MarshalIndent(tbResult, "", " ")
				log.Printf("%s = %s", name, s)
			}

			snmpTables[name] = tbResult
		}
	}

	// call mapping.js to convert snmpTables to device.boards[]
	deviceInst.Boards = make([]*Board, 0, 10)
	mapper.MapBoards(deviceInst, snmpTables)
}
