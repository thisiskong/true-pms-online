package snmplib2

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"strconv"
	"strings"
	"time"
)

func (transform *Transform) transform(target *SnmpTarget, row *PollRecord) {
	if transform.TransformObjType == "olt-pon-traffic" {
		transform_olt_pon_traffic(target, row)

	} else if transform.TransformObjType == "onu-pon" {
		transform_onu_pon(target, row)

	} else if transform.TransformObjType == "olt-uplink" {
		transform_olt_uplink(target, row)

	} else if transform.TransformObjType == "olt-pon" {
		transform_olt_pon(target, row)

	} else {
		log.Printf("Unknown TransformObjType: %s", transform.TransformObjType)
	}
}

func transform_olt_pon_traffic(target *SnmpTarget, row *PollRecord) {
	// s, _ := json.MarshalIndent(row, "", " ")
	// log.Printf("%s", s)

	// in_octets, out_octets
	if target.Network == "FTTx" && target.Vendor == "ZTE" {
		// in_octets 	= zte_in_octets + zte_in_octets1490 + zte_in_octets1577
		// out_octets = zte_out_octets + zte_out_octets1490 + zte_out_octets1577
		var zte_in_octets uint64 = 0
		var zte_in_octets1490 uint64 = 0
		var zte_in_octets1577 uint64 = 0
		var zte_out_octets uint64 = 0
		var zte_out_octets1490 uint64 = 0
		var zte_out_octets1577 uint64 = 0

		zte_in_octets, _ = row.Values["zte_in_octets"].(uint64)
		zte_in_octets1490, _ = row.Values["zte_in_octets1490"].(uint64)
		zte_in_octets1577, _ = row.Values["zte_in_octets1577"].(uint64)
		zte_out_octets, _ = row.Values["zte_out_octets"].(uint64)
		zte_out_octets1490, _ = row.Values["zte_out_octets1490"].(uint64)
		zte_out_octets1577, _ = row.Values["zte_out_octets1577"].(uint64)

		in_octets := zte_in_octets + zte_in_octets1490 + zte_in_octets1577
		out_octets := zte_out_octets + zte_out_octets1490 + zte_out_octets1577

		ifspeed := row.Fields.IfSpeed
		if row.Meas > 0 {
			// compute wire speed (octets)
			limit := uint64(row.Meas) * uint64(row.Fields.IfSpeed) / 8
			if in_octets < limit && out_octets < limit {
				row.Values["in_octets"] = in_octets
				row.Values["out_octets"] = out_octets

				// rate in bit-per-sec
				in_rate := int64(in_octets / uint64(row.Meas) * 8)
				row.Values["in_rate"] = in_rate
				if ifspeed > 0 {
					in_bw := (float64(in_rate) / float64(ifspeed)) * 100
					row.Values["in_bw"] = in_bw
				}
				out_rate := int64(out_octets / uint64(row.Meas) * 8)
				row.Values["out_rate"] = out_rate
				if ifspeed > 0 {
					out_bw := (float64(out_rate) / float64(ifspeed)) * 100
					row.Values["out_bw"] = out_bw
				}
				log.Printf("zte-pon-traffic: %s|%s|%s in_octets: %v|%v|ok", target.IP, row.Fields.PonPort, row.Fields.IfIndex, in_octets, limit)
				log.Printf("zte-pon-traffic: %s|%s|%s out_octets: %v|%v|ok", target.IP, row.Fields.PonPort, row.Fields.IfIndex, out_octets, limit)
			} else {
				log.Printf("zte-pon-traffic: %s|%s|%s in_octets: %v|%v|drop", target.IP, row.Fields.PonPort, row.Fields.IfIndex, in_octets, limit)
				log.Printf("zte-pon-traffic: %s|%s|%s out_octets: %v|%v|drop", target.IP, row.Fields.PonPort, row.Fields.IfIndex, out_octets, limit)
			}
		}

		// s, _ := json.Marshal(row)
		// log.Printf("zte-pon-traffic: %s|%s row=%s", target.IP, row.Fields.IfIndex, s)
		// log.Printf("zte-pon-traffic: %s|%s|%s in_octets: %v = %v + %v + %v", target.IP, row.Fields.IfIndex, row.Fields.IfName, in_octets, zte_in_octets, zte_in_octets1490, zte_in_octets1577)
		// log.Printf("zte-pon-traffic: %s|%s out_octets: %v = %v + %v + %v", target.IP, row.Fields.IfIndex, out_octets, zte_out_octets, zte_out_octets1490, zte_out_octets1577)

	} else {
		ifspeed := row.Fields.IfSpeed
		in_octets := row.Values["in_octets"]
		out_octets := row.Values["out_octets"]
		if row.Meas > 0 {
			// rate in bit-per-sec
			if in_octets != nil {
				in_rate := int64(in_octets.(uint64) / uint64(row.Meas) * 8)
				row.Values["in_rate"] = in_rate
				if ifspeed > 0 {
					in_bw := (float64(in_rate) / float64(ifspeed)) * 100
					row.Values["in_bw"] = in_bw
				}
			}
			if out_octets != nil {
				out_rate := int64(out_octets.(uint64) / uint64(row.Meas) * 8)
				row.Values["out_rate"] = out_rate
				if ifspeed > 0 {
					out_bw := (float64(out_rate) / float64(ifspeed)) * 100
					row.Values["out_bw"] = out_bw
				}
			}
		}
	}

	// packets
	in_ucast_pkt := row.Values["in_ucast_pkt"]
	in_bcast_pkt := row.Values["in_bcast_pkt"]
	in_mcast_pkt := row.Values["in_mcast_pkt"]
	in_err := row.Values["in_err"]
	if in_ucast_pkt != nil && in_bcast_pkt != nil && in_mcast_pkt != nil && in_err != nil {
		in_pkt := in_ucast_pkt.(uint64) + in_bcast_pkt.(uint64) + in_mcast_pkt.(uint64) + in_err.(uint64)
		row.Values["in_pkt"] = in_pkt
		if in_pkt > 0 {
			row.Values["in_ucast_pct"] = (float64(in_ucast_pkt.(uint64)) / float64(in_pkt)) * 100
			row.Values["in_bcast_pct"] = (float64(in_bcast_pkt.(uint64)) / float64(in_pkt)) * 100
			row.Values["in_mcast_pct"] = (float64(in_mcast_pkt.(uint64)) / float64(in_pkt)) * 100
			row.Values["in_err_pct"] = (float64(in_err.(uint64)) / float64(in_pkt)) * 100
		} else {
			row.Values["in_ucast_pct"] = float64(0)
			row.Values["in_bcast_pct"] = float64(0)
			row.Values["in_mcast_pct"] = float64(0)
		}
	}
	out_ucast_pkt := row.Values["out_ucast_pkt"]
	out_bcast_pkt := row.Values["out_bcast_pkt"]
	out_mcast_pkt := row.Values["out_mcast_pkt"]
	if out_ucast_pkt != nil && out_bcast_pkt != nil && out_mcast_pkt != nil {
		out_pkt := out_ucast_pkt.(uint64) + out_bcast_pkt.(uint64) + out_mcast_pkt.(uint64)
		row.Values["out_pkt"] = out_pkt
		if out_pkt > 0 {
			row.Values["out_ucast_pct"] = (float64(out_ucast_pkt.(uint64)) / float64(out_pkt)) * 100
			row.Values["out_bcast_pct"] = (float64(out_bcast_pkt.(uint64)) / float64(out_pkt)) * 100
			row.Values["out_mcast_pct"] = (float64(out_mcast_pkt.(uint64)) / float64(out_pkt)) * 100
		} else {
			row.Values["out_ucast_pct"] = float64(0)
			row.Values["out_bcast_pct"] = float64(0)
			row.Values["out_mcast_pct"] = float64(0)
		}
	}
}

func transform_onu_pon(target *SnmpTarget, row *PollRecord) {
	// Fiberhome
	if target.Vendor == "Fiberhome" {

		// onu-pon-fbh1
		row.set_int("fbh_onu_ranging", "ranging", 0, 65535)
		// row.set_int_x_float("fbh_onu_txpwr", "onu_txpwr", 0.01)
		// row.set_int_x_float("fbh_onu_rxpwr", "onu_rxpwr", 0.01)
		// row.set_int_x_float("fbh_onu_current", "onu_current", 0.01)
		// row.set_int_x_float("fbh_onu_voltage", "onu_voltage", 0.01)
		// row.set_int_x_float("fbh_onu_temp", "onu_temp", 0.01)
		// row.set_str("fbh_onu_status", "onu_status")
		// row.set_str_uppercase("fbh_onu_serial", "onu_serial")
		row.set_datetime("fbh_onu_lastuptime", "onu_lastuptime")
		row.set_datetime("fbh_onu_lastdowntime", "onu_lastdowntime")
		row.set_fbh_onulastdowncause("fbh_onu_lastdowncause", "onu_lastdowncause")

		// onu-pon-fbh2
		row.set_int_x_float("fbh_pon_rxpwr", "pon_rxpwr", 0.01, -65534, 65534)

		// s, _ := json.MarshalIndent(row, "", " ")
		// log.Printf("%s", s)

	} else if target.Vendor == "ZTE" {

		row.set_zte_dBuW_to_dBm("zte_pon_rxpwr", "pon_rxpwr")
		row.set_int("zte_onu_ranging", "ranging", 0, 65535)
		row.set_str("zte_onu_status", "onu_status")
		row.set_str_uppercase("zte_onu_serial", "onu_serial")
		row.set_hex2datetime("zte_onu_lastuptime", "onu_lastuptime")
		row.set_hex2datetime("zte_onu_lastdowntime", "onu_lastdowntime")
		row.set_str("zte_onu_lastdowncause", "onu_lastdowncause")

		row.set_zte_dBuW_to_dBm("zte_onu_txpwr", "onu_txpwr")
		row.set_zte_dBuW_to_dBm("zte_onu_rxpwr", "onu_rxpwr")
		row.set_int_x_float("zte_onu_current", "onu_current", 2*0.001, 1, 2147483647)
		row.set_int_x_float("zte_onu_voltage", "onu_voltage", 20*0.001, 1, 2147483647)
		row.set_int_x_float("zte_onu_temp", "onu_temp", 0.001, 1, 2147483647)

		// rxpwr at OLT
		row.set_int_x_float("zte_pon_rxpwr", "pon_rxpwr", 0.001, -2147483647, 2147483647)

	} else if target.Vendor == "Huawei" {

		row.set_hua_dBm("hua_pon_rxpwr", "pon_rxpwr")
		row.set_int("hua_onu_ranging", "ranging", 0, 65535)
		row.set_hex2datetime("hua_onu_lastuptime", "onu_lastuptime")
		row.set_hex2datetime("hua_onu_lastdowntime", "onu_lastdowntime")
		row.set_str("hua_onu_lastdowncause", "onu_lastdowncause")

		row.set_hua_onu_out_pkterr()
		row.set_hua_onu_in_pkterr()

		s, _ := json.Marshal(row)
		log.Printf("%s", s)

	} else if target.Vendor == "Nokia" {

		row.set_int_x_float("nok_pon_rxpwr", "pon_rxpwr", 0.1, -65533, 65533) // drop if value >= 65534, val*0.1
		row.set_int_x_int("nok_onu_ranging", "ranging", 100, -65533, 65533)   // drop if value >= 65534, val*100
		row.set_str("nok_onu_lastdowncause", "onu_lastdowncause")

	} else if target.Vendor == "Dasan" {

		row.set_int("dsn_onu_ranging", "ranging", 0, 65535)
		row.set_dsn_str_as_float("dsn_onu_rxpwr", "onu_rxpwr")
		row.set_dsn_str_as_float("dsn_onu_txpwr", "onu_txpwr")
		row.set_str("dsn_onu_serial", "onu_serial")
		row.set_str("dsn_onu_status", "onu_status")
		row.set_dsn_str_as_float("dsn_onu_current", "onu_current")
		row.set_dsn_str_as_float("dsn_onu_voltage", "onu_voltage")
		row.set_dsn_str_as_float("dsn_onu_temp", "onu_temp")

		// dsn_onu_lastuptime
		row.set_dsn_datetime("dsn_onu_lastuptime", "onu_lastuptime")
		row.set_dsn_datetime("dsn_onu_lastdowntime", "onu_lastdowntime")
		row.set_str("dsn_onu_lastdowncause", "onu_lastdowncause")

		// s, _ := json.MarshalIndent(row, "", " ")
		// log.Printf("%s", s)
	}

	// s, _ := json.MarshalIndent(row, "", " ")
	// log.Printf("%s", s)
}

func transform_olt_uplink(target *SnmpTarget, row *PollRecord) {
	// Fiberhome
	if target.Vendor == "Fiberhome" {
		ifname, ok := row.Values["ifName"].(string)
		if !ok {
			return
		}
		intf, ok := target.InterfacesIfName[ifname]
		if !ok {
			return
		}
		row.Fields.IfIndex = intf.Ifindex
		row.Fields.IfName = intf.Ifname
		row.Fields.IfSpeed = intf.Ifspeed
		row.Fields.IfOper = intf.Ifoper

		row.set_int_x_float("olt_fbh_uplink_txpwr", "txpwr", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("olt_fbh_uplink_rxpwr", "rxpwr", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("olt_fbh_uplink_current", "current", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("olt_fbh_uplink_voltage", "voltage", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("olt_fbh_uplink_temp", "temp", 0.01, 0, 2147483647)

	} else if target.Vendor == "ZTE" {
		intf, ok := target.InterfacesIfIndex[row.RowId]
		if ok {
			row.Fields.IfIndex = intf.Ifindex
			row.Fields.IfName = intf.Ifname
			row.Fields.IfSpeed = intf.Ifspeed
			row.Fields.IfOper = intf.Ifoper
		}

		row.set_int_x_float("olt_zte_uplink_txpwr", "txpwr", 0.001, -2147483646, 2147483646)     // if value != 2147483647
		row.set_int_x_float("olt_zte_uplink_rxpwr", "rxpwr", 0.001, -2147483646, 2147483646)     // if value != 2147483647
		row.set_int_x_float("olt_zte_uplink_current", "current", 0.001, -2147483646, 2147483646) // if value != 2147483647
		row.set_int_x_float("olt_zte_uplink_voltage", "voltage", 0.001, -2147483646, 2147483646) // if value != 2147483647
		row.set_int_x_float("olt_zte_uplink_temp", "temp", 0.001, 0, 65535)

	} else if target.Vendor == "Huawei" {
		intf, ok := target.InterfacesIfIndex[row.RowId]
		if ok {
			row.Fields.IfIndex = intf.Ifindex
			row.Fields.IfName = intf.Ifname
			row.Fields.IfSpeed = intf.Ifspeed
			row.Fields.IfOper = intf.Ifoper
		}

		row.set_int_x_float("olt_hua_uplink_txpwr", "txpwr", 0.000001, -2147483646, 2147483646)     // if value != 2147483647
		row.set_int_x_float("olt_hua_uplink_rxpwr", "rxpwr", 0.000001, -2147483646, 2147483646)     // if value != 2147483647
		row.set_int_x_float("olt_hua_uplink_current", "current", 0.000001, -2147483646, 2147483646) // if value != 2147483647
		row.set_int_x_float("olt_hua_uplink_voltage", "voltage", 0.000001, -2147483646, 2147483646) // if value != 2147483647
		row.set_int_x_float("olt_hua_uplink_temp", "temp", 0.000001, 0, 2147483646)                 // if value != 2147483647

	} else if target.Vendor == "Nokia" {

		setFieldsNokia_olt_uplink(target, row)

		row.set_str_as_float("olt_nok_uplink_txpwr", "txpwr", " dBm", "%f dBm")                       // "3.49 dBm" or "No Power"
		row.set_str_as_float("olt_nok_uplink_rxpwr", "rxpwr", " dBm", "%f dBm")                       // "3.49 dBm" or "No Power"
		row.set_str_as_float("olt_nok_uplink_current", "current", " mA", "%f mA")                     // 39.20 mA
		row.set_str_as_float("olt_nok_uplink_voltage", "voltage", " VDC", "%f VDC")                   // 3.36 VDC
		row.set_str_as_float("olt_nok_uplink_temp", "temp", " degrees Celsius", "%f degrees Celsius") // 47.95 degrees Celsius

	} else if target.Vendor == "Dasan" {
		intf, ok := target.InterfacesIfIndex[row.RowId]
		if ok {
			row.Fields.IfIndex = intf.Ifindex
			row.Fields.IfName = intf.Ifname
			row.Fields.IfSpeed = intf.Ifspeed
			row.Fields.IfOper = intf.Ifoper
		}

		// olt_dsn_uplink_txpwr		= "3.8059" or "N/A"
		// olt_dsn_uplink_rxpwr 	= "-22.8400" or "N/A"
		// olt_dsn_uplink_current = "10.3860" or "N/A"
		// olt_dsn_uplink_voltage	= "3.2312" or "N/A"
		// olt_dsn_uplink_temp		= "49.0625" or "N/A"

		row.set_dsn_str_as_float("olt_dsn_uplink_txpwr", "txpwr")
		row.set_dsn_str_as_float("olt_dsn_uplink_rxpwr", "rxpwr")
		row.set_dsn_str_as_float("olt_dsn_uplink_current", "current")
		row.set_dsn_str_as_float("olt_dsn_uplink_voltage", "voltage")
		row.set_dsn_str_as_float("olt_dsn_uplink_temp", "temp")

		// s, _ := json.MarshalIndent(row, "", " ")
		// log.Printf("%s", s)
	}
}

func transform_olt_pon(target *SnmpTarget, row *PollRecord) {
	// Fiberhome
	if target.Vendor == "Fiberhome" {
		ifname, ok := row.Values["fbh_pon_ifname"].(string)
		if !ok {
			return
		}
		ponport, ok := target.PonPortsIfName[ifname]
		if !ok {
			return
		}

		row.Fields.IfIndex = ponport.Ifindex
		row.Fields.IfName = ponport.Ifname
		row.Fields.IfSpeed = ponport.Ifspeed
		row.Fields.IfOper = ponport.Ifoper
		row.Fields.PonPort = ponport.PonPort

		row.set_int_x_float("fbh_pon_txpwr1490", "pon_txpwr1490", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("fbh_pon_txpwr1577", "pon_txpwr1577", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("fbh_pon_current1490", "pon_current1490", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("fbh_pon_current1577", "pon_current1577", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("fbh_pon_voltage", "pon_voltage", 0.01, -2147483647, 2147483647)
		row.set_int_x_float("fbh_pon_temp", "pon_temp", 0.01, 0, 2147483647)

	} else if target.Vendor == "Huawei" {
		ponport, ok := target.PonPortsIfIndex[row.RowId]
		if !ok {
			return
		}

		row.Fields.IfIndex = ponport.Ifindex
		row.Fields.IfName = ponport.Ifname
		row.Fields.IfSpeed = ponport.Ifspeed
		row.Fields.IfOper = ponport.Ifoper
		row.Fields.PonPort = ponport.PonPort

		row.set_int_x_float("hua_pon_txpwr1490", "pon_txpwr1490", 0.01, -2147483646, 2147483646)
		row.set_int_x_float("hua_pon_txpwr1577", "pon_txpwr1577", 0.01, -2147483646, 2147483646)
		row.set_int("hua_pon_current1490", "pon_current1490", 0, 65535)
		row.set_int_x_float("hua_pon_current1577", "pon_current1577", 0.001, -2147483646, 2147483646)
		row.set_int_x_float("hua_pon_voltage", "pon_voltage", 0.01, -2147483646, 2147483646)
		row.set_int("hua_pon_temp", "pon_temp", 0, 65535)

	} else if target.Vendor == "ZTE" {
		ponport, ok := target.PonPortsIfIndex[row.Fields.IfIndex]
		if !ok {
			return
		}

		row.Fields.IfIndex = ponport.Ifindex
		row.Fields.IfName = ponport.Ifname
		row.Fields.IfSpeed = ponport.Ifspeed
		row.Fields.IfOper = ponport.Ifoper
		row.Fields.PonPort = ponport.PonPort

		// dual channel
		row.set_int_x_float2("zte_pon_dual_current1490", "zte_pon_current1490", "pon_current1490", 0.001, -2147483646, 2147483646)
		row.set_int_x_float2("zte_pon_dual_txpwr1490", "zte_pon_txpwr1490", "pon_txpwr1490", 0.001, -2147483646, 2147483646)

		row.set_int_x_float("zte_pon_dual_current1577", "pon_current1577", 0.001, -2147483646, 2147483646)
		row.set_int_x_float("zte_pon_dual_txpwr1577", "pon_txpwr1577", 0.001, -2147483646, 2147483646)

		row.set_int_x_float("zte_pon_voltage", "pon_voltage", 0.001, -2147483646, 2147483646)
		row.set_int_x_float("zte_pon_temp", "pon_temp", 0.001, -2147483646, 2147483646)

	} else if target.Vendor == "Nokia" {

		ponport, ok := target.PonPortsNokiaPonId[row.RowId]
		if !ok {
			return
		}

		row.Fields.IfIndex = ponport.Ifindex
		row.Fields.IfName = ponport.Ifname
		row.Fields.IfSpeed = ponport.Ifspeed
		row.Fields.IfOper = ponport.Ifoper
		row.Fields.PonPort = ponport.PonPort

		row.set_str_as_float("nok_pon_txpwr1490", "pon_txpwr1490", " dBm", "%f dBm")               // "3.49 dBm" or "No Power"
		row.set_str_as_float("nok_pon_current1490", "pon_current1490", " mA", "%f mA")             // 39.20 mA
		row.set_str_as_float("nok_pon_voltage", "pon_voltage", " VDC", "%f VDC")                   // 3.36 VDC
		row.set_str_as_float("nok_pon_temp", "pon_temp", " degrees Celsius", "%f degrees Celsius") // 47.95 degrees Celsius

	} else if target.Vendor == "Dasan" {

		// Dasan report stats with same OID for both olt-uplink and olt-pon
		// Therefore, we need to filter out olt-pon and drop olt-uplink
		ponport, ok := target.PonPortsIfIndex[row.Fields.IfIndex]
		if !ok {
			return
		}

		row.Fields.IfIndex = ponport.Ifindex
		row.Fields.IfName = ponport.Ifname
		row.Fields.IfSpeed = ponport.Ifspeed
		row.Fields.IfOper = ponport.Ifoper
		row.Fields.PonPort = ponport.PonPort

		// dsn_pon_txpwr1490		= "3.8059" or "N/A"
		// dsn_pon_rxpwr		 		= "-22.8400" or "N/A"
		// dsn_pon_current1490 	= "10.3860" or "N/A"
		// dsn_pon_voltage			= "3.2312" or "N/A"
		// dsn_pon_temp					= "49.0625" or "N/A"

		row.set_dsn_str_as_float("dsn_pon_txpwr1490", "pon_txpwr1490")
		row.set_dsn_str_as_float("dsn_pon_current1490", "pon_current1490")
		row.set_dsn_str_as_float("dsn_pon_voltage", "pon_voltage")
		row.set_dsn_str_as_float("dsn_pon_temp", "pon_temp")

		// Only Dasan report pon_rxpwr at olt-pon port, Others vendor report at onu-pon port
		row.set_dsn_str_as_float("dsn_pon_rxpwr", "pon_rxpwr")

		// s, _ := json.MarshalIndent(row, "", " ")
		// log.Printf("%s", s)
	}
}

func setFieldsNokia_olt_uplink(target *SnmpTarget, row *PollRecord) {
	if row.RowId == "257" {
		intf, ok := target.InterfacesIfIndex["131072"]
		if ok {
			row.Fields.IfIndex = intf.Ifindex
			row.Fields.IfName = intf.Ifname
			row.Fields.IfSpeed = intf.Ifspeed
			row.Fields.IfOper = intf.Ifoper
		}
	} else if row.RowId == "258" {
		intf, ok := target.InterfacesIfIndex["262144"]
		if ok {
			row.Fields.IfIndex = intf.Ifindex
			row.Fields.IfName = intf.Ifname
			row.Fields.IfSpeed = intf.Ifspeed
			row.Fields.IfOper = intf.Ifoper
		}
	}
}

func (row *PollRecord) set_int(src string, dst string, min int64, max int64) {
	val, ok := row.Values[src].(int64)
	if !ok {
		return
	}
	if val < min || val > max {
		// ignore if value out of range
		return
	}
	row.Values[dst] = val
}

func (row *PollRecord) set_zte_dBuW_to_dBm(src string, dst string) {
	val, ok := row.Values[src].(int64)
	if !ok {
		return
	}
	// drop if val == -80000 or val == 65535000
	if val == -80000 || val == 65535000 {
		return
	}
	row.Values[dst] = (float64(val) * 0.002) - 30
}

func (row *PollRecord) set_hua_dBm(src string, dst string) {
	val, ok := row.Values[src].(int64)
	if !ok {
		return
	}
	if val == 2147483647 {
		// ignore max value
		return
	}
	row.Values[dst] = (float64(val) - 10000) / 100
}

func (row *PollRecord) set_int_x_int(src string, dst string, multipler int64, min int64, max int64) {
	val, ok := row.Values[src].(int64)
	if !ok {
		return
	}
	if val < min || val > max {
		return
	}
	row.Values[dst] = val * multipler
}

func (row *PollRecord) set_int_x_float2(src1 string, src2 string, dst string, multipler float64, min int64, max int64) {
	val, ok := row.Values[src1].(int64)
	if !ok {
		val, ok = row.Values[src2].(int64)
		if !ok {
			return
		}
	}
	if val < min || val > max {
		return
	}
	row.Values[dst] = float64(val) * multipler
}

func (row *PollRecord) set_int_x_float(src string, dst string, multipler float64, min int64, max int64) {
	val, ok := row.Values[src].(int64)
	if !ok {
		return
	}
	if val < min || val > max {
		return
	}
	row.Values[dst] = float64(val) * multipler
}

func (row *PollRecord) set_uint64(src string, dst string) {
	val, ok := row.Values[src].(uint64)
	if !ok {
		return
	}
	row.Values[dst] = val
}

func (row *PollRecord) set_str(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	row.Values[dst] = val
}

func (row *PollRecord) set_str_uppercase(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	row.Values[dst] = strings.ToUpper(val)
}

func (row *PollRecord) set_fbh_onulastdowncause(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	// 0: none
	// 1: ONU link loss
	// 2: power failure
	// 3: offline
	// 4: link loss on OLT’s PON port
	// -----------------------------------
	// 2024-12-19 14:45:32,2024-12-22 09:18:56,2;2024-11-29 13:51:35,2024-12-19 14:45:24,1;2024-11-29 11:24:43,2024-11-29 13:51:25,1;2024-11-05 16:36:05,2024-11-29 09:00:52,2;2024-09-28 20:34:51,2024-11-05 16:19:55,2;2024-08-14 22:10:41,2024-09-28 20:34:12,2;2024-08-05 21:48:05,2024-08-14 22:10:07,2;2024-08-03 12:21:38,2024-08-05 21:47:30,2;2024-08-01 06:38:04,2024-08-03 12:21:02,2;2024-06-24 11:15:57,2024-08-01 06:37:27,2
	// -----------------------------------
	// 2024-12-19 14:45:32,2024-12-22 09:18:56,2
	// 2024-11-29 13:51:35,2024-12-19 14:45:24,1
	// 2024-11-29 11:24:43,2024-11-29 13:51:25,1
	// 2024-11-05 16:36:05,2024-11-29 09:00:52,2
	// 2024-09-28 20:34:51,2024-11-05 16:19:55,2
	// 2024-08-14 22:10:41,2024-09-28 20:34:12,2
	// 2024-08-05 21:48:05,2024-08-14 22:10:07,2
	// 2024-08-03 12:21:38,2024-08-05 21:47:30,2
	// 2024-08-01 06:38:04,2024-08-03 12:21:02,2
	// 2024-06-24 11:15:57,2024-08-01 06:37:27,2
	// log.Printf("set_fbh_onulastdowncause=%v", val)
	for _, token := range strings.Split(val, ";") {
		values := strings.Split(token, ",")
		if len(values) == 3 {
			// dt1 := values[0]
			// dt2 := values[1]
			strvalue := ""
			switch values[2] {
			case "0":
				strvalue = "None"
				break
			case "1":
				strvalue = "ONU LinkLoss"
				break
			case "2":
				strvalue = "Power Failure"
				break
			case "3":
				strvalue = "Offline"
				break
			case "4":
				strvalue = "PON LinkLoss"
				break
			}
			// take only first row
			row.Values[dst] = strvalue
			return
		}
	}
}

func (row *PollRecord) set_datetime(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	// 2025-02-22 11:02:23
	// log.Printf("set_datetime=%v", val)
	dt, err := time.Parse("2006-01-02 15:04:05", val)
	if err == nil {
		row.Values[dst] = dt
	}
}

func (row *PollRecord) set_hex2datetime(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	// Hex-STRING: 00 00 00 00 00 00 00 00
	// Hex-STRING: 00 00 00 00 00 00 00 00 00 00 00
	if strings.HasPrefix(val, "0000") {
		return
	}
	// Hex-STRING: 07 E9 02 14 02 3A 33 00
	// Hex-STRING: 07 E9 02 1A 0E 09 14 00 2B 07 00
	data, err := hex.DecodeString(val)
	if err != nil {
		log.Fatalf("Failed to decode hex string: {%v}, %v", hex.EncodeToString([]byte(val)), err)
	}

	// Extract the components
	year := int(data[0])<<8 | int(data[1]) // Combine the first two bytes for the year
	month := time.Month(data[2])           // Convert to time.Month
	day := int(data[3])
	hour := int(data[4])
	minute := int(data[5])
	second := int(data[6])

	dt := time.Date(year, month, day, hour, minute, second, 0, time.UTC)
	row.Values[dst] = dt
	// log.Printf("set_hex2datetime: {%v} = %v", hex.EncodeToString([]byte(val)), dt)
}

func (row *PollRecord) set_str_as_float(src string, dst string, contains string, pattern string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}
	// "3.49 dBm" or "No Power"
	// contains = " dBm"
	// pattern  = "%f dBm"
	if strings.Contains(val, contains) {
		var value float64
		_, err := fmt.Sscanf(val, pattern, &value)
		if err == nil {
			row.Values[dst] = value
		} else {
			log.Printf("Error: %v", err)
		}
	}
}

func (row *PollRecord) set_dsn_str_as_float(src string, dst string) {
	val, ok := row.Values[src].(string)
	if !ok {
		return
	}

	// olt_dsn_uplink_txpwr		= "3.8059" or "N/A"
	// olt_dsn_uplink_rxpwr 	= "-22.8400" or "N/A"
	// olt_dsn_uplink_current = "10.3860" or "N/A"
	// olt_dsn_uplink_voltage	= "3.2312" or "N/A"
	// olt_dsn_uplink_temp		= "49.0625" or "N/A"

	if "N/A" == val {
		return
	}
	floatVal, err := strconv.ParseFloat(val, 64)
	if err == nil {
		row.Values[dst] = floatVal
	} else {
		log.Printf("Error: %v", err)
	}
}

func (row *PollRecord) set_dsn_datetime(src string, dst string) {
	lastuptime, ok := row.Values[src]
	if ok {
		seconds := lastuptime.(uint64)
		if seconds > 0 {
			lastuptime_date := time.Now().Add(-time.Duration(seconds) * time.Second)
			dt := lastuptime_date.Format("2006-01-02 15:04:05")
			row.Values[dst] = dt
			// log.Printf("%v|%v|%v|%v|%v", row.Fields.PonPort, row.Fields.OntId, src, lastuptime, dt)
		}
	}
}

func (row *PollRecord) set_hua_onu_out_pkterr() {
	var val1, val2, val3, val4 int64 = 0, 0, 0, 0
	val1, _ = row.Values["hua_onu_out_pkterr1"].(int64)
	val2, _ = row.Values["hua_onu_out_pkterr2"].(int64)
	val3, _ = row.Values["hua_onu_out_pkterr3"].(int64)
	val4, _ = row.Values["hua_onu_out_pkterr4"].(int64)
	val := val1 + val2 + val3 + val4
	row.Values["onu_out_pkterr"] = val
}

func (row *PollRecord) set_hua_onu_in_pkterr() {
	var val1, val2, val3, val4 int64 = 0, 0, 0, 0
	val1, _ = row.Values["hua_onu_in_pkterr1"].(int64)
	val2, _ = row.Values["hua_onu_in_pkterr2"].(int64)
	val3, _ = row.Values["hua_onu_in_pkterr3"].(int64)
	val4, _ = row.Values["hua_onu_in_pkterr4"].(int64)
	val := val1 + val2 + val3 + val4
	row.Values["onu_in_pkterr"] = val
}
