package snmplib2

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"log"
	"math/big"
	"strings"
	"unicode"

	"github.com/gosnmp/gosnmp"
)

func ToValue(snmpOid *SnmpOid, pdu gosnmp.SnmpPDU) (interface{}, error) {
	// log.Printf("ToValue %v = %v {%v} {%v} {%v}", pdu.Name, pdu.Value, pdu.Type, reflect.TypeOf(pdu.Value), snmpOid.Name)
	switch pdu.Type {
	case gosnmp.TimeTicks, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Uinteger32:
		// 0..4294967295
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64(), nil
	case gosnmp.Counter64:
		// 0..18446744073709551615
		val := gosnmp.ToBigInt(pdu.Value)
		return val.Uint64(), nil
	case gosnmp.Integer:
		// -2147483648..2147483647
		val := gosnmp.ToBigInt(pdu.Value)
		if snmpOid.Enum != nil {
			// log.Printf("enum: %v, %v", bigInt.Int64(), snmpOid.Enum)
			enum, ok := snmpOid.Enum[int(val.Int64())]
			if ok {
				return enum, nil
			} else {
				return fmt.Sprintf("%d", val.Int64()), nil
			}
		} else {
			return val.Int64(), nil
		}
	case gosnmp.OctetString, gosnmp.IPAddress:
		if byteArray, ok := pdu.Value.([]byte); ok {
			// There's a case for Nokia OLT that ifHCInOctets & ifHCOutOctets for Uplink port use String type instead of Counter64
			// We check if incoming type is String and SnmpOid.Name either ifHCInOctets or ifHCOutOCtets
			// then convert HexString to Uint64
			if snmpOid.Syntax == "HexString" {
				hexStr := hex.EncodeToString(byteArray)
				val := new(big.Int)
				_, ok := val.SetString(hexStr, 16)
				if ok {
					// log.Printf("hexString={0x%v} = %v", hexStr, val)
					return val.Uint64(), nil
				}
				return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)

			} else if snmpOid.Syntax == "PhysAddress" {
				addr := []string{}
				for i := 0; i < len(byteArray); i++ {
					addr = append(addr, hex.EncodeToString([]byte{byteArray[i]}))
				}
				return strings.Join(addr, ":"), nil

			} else if snmpOid.Syntax == "EncodeToString" {
				// Some device return datetime as HexString [7 232 12 24 15 0 56 0]
				// However, if byteArray = [0 0 0 0 0 0 0 0]
				// isASCII(string(byteArray)) will return True and the output is incorrect
				// set syntax = "EncodeToString" will always use hex.EncodeToString()
				return hex.EncodeToString(byteArray), nil
			} else if snmpOid.Syntax == "DecodeONUSerial" {
				// Convert to ONU Serail No
				return decodeONUSerial(byteArray), nil
			} else {
				if isASCII(byteArray) {
					return string(byteArray), nil
				} else {
					return hex.EncodeToString(byteArray), nil
				}
			}
		}
		if strValue, ok := pdu.Value.(string); ok {
			return strValue, nil
		}
		return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)
	case gosnmp.ObjectIdentifier:
		return pdu.Value, nil
	case gosnmp.EndOfContents:
		return nil, nil
	case gosnmp.EndOfMibView:
		return nil, nil
	case gosnmp.NoSuchInstance:
		return nil, fmt.Errorf("NoSuchInstance: name=%v, type=%v", pdu.Name, pdu.Type)
	case gosnmp.NoSuchObject:
		return nil, fmt.Errorf("NoSuchObject: name=%v, type=%v", pdu.Name, pdu.Type)
	default:
		return nil, fmt.Errorf("failed to convert name=%v, type=%v", pdu.Name, pdu.Type)
	}
}

func decodeONUSerial(byteArray []byte) string {
	if len(byteArray) < 4 {
		// invalid data, return value as hex-string
		// return hex.EncodeToString(byteArray)
		// invalid data
		return ""
	}
	// First 4 characters: Vendor ID
	if bytes.Equal(byteArray[:4], []byte{0, 0, 0, 0}) {
		// [0 0 0 0 0 0 0 0]
		// invalid data
		// log.Printf("decodeONUSerial: {%v} = nil", byteArray)
		return ""
	}
	// First 4 characters: Vendor ID
	vendorID := string(byteArray[:4])
	// Remaining characters: Serial Number
	serialNum := hex.EncodeToString(byteArray[4:])
	onuSerial := vendorID + serialNum
	// log.Printf("decodeONUSerial: {%v} = {%v}", byteArray, onuSerial)
	return onuSerial
}

func PrintValue(pdu gosnmp.SnmpPDU) error {
	log.Printf("%-30s = ", pdu.Name)
	switch pdu.Type {
	case gosnmp.OctetString:
		byteArray := pdu.Value.([]byte)
		if isASCII(byteArray) {
			log.Printf("{string} %s\n", string(byteArray))
		} else {
			encodedString := hex.EncodeToString(byteArray)
			log.Printf("{ipaddr} %s\n", encodedString)
		}
	default:
		log.Printf("{number} %d\n", gosnmp.ToBigInt(pdu.Value))
	}
	return nil
}

func isASCII(value []byte) bool {
	for _, c := range value {
		if c > unicode.MaxASCII {
			return false
		}
	}
	return true
}

func isEndOfOid(variables *[]gosnmp.SnmpPDU, oid string) bool {
	if len(*variables) == 0 {
		return true
	}
	for _, variable := range *variables {
		if !strings.HasPrefix(variable.Name, oid+".") {
			return true
		}
	}
	return false
}

func getLimit(field *TransformField, meas int, ifSpeed int64) *uint64 {
	// There's issue with FTTx ZTE for pontraffic60m
	// 1.) counter suddendly reset to 0 then increase in subsequence polling
	// 2.) counter suddently jump to exceed 100% then decrease in subsquence polling
	if field.Name == "ifHCInOctets" || field.Name == "ifHCOutOctets" ||
		field.Name == "zte_in_octets" || field.Name == "zte_in_octets1490" || field.Name == "zte_in_octets1577" ||
		field.Name == "zte_out_octets" || field.Name == "zte_out_octets1490" || field.Name == "zte_out_octets1577" {
		// compute limit from wire speed and convert to octets
		// octets = meas x (ifspeed (bit-per-sec) / 8)
		limit := uint64(meas) * uint64(ifSpeed) / 8
		return &limit
		// --- There's a case where ifHighSpeed does not return value for this polling which cause error when process delta value ---
		// ifspeed, ok := row.Values["ifHighSpeed"]
		// if ok {
		// 	if ifspeed.Value != nil {
		// 		limit := uint64(meas) * ifspeed.Value.(uint64) / 8 * 1000000
		// 		// log.Printf("name: %s, ifHighSpeed=%v, meas=%d, limit=%d", dtconfig.Name, val.Value, meas, limit)
		// 		return &limit
		// 	} else {
		// 		log.Printf("Error! getLimit: name=%v, ifspeed is nil", dtconfig.Name)
		// 		return dtconfig.Limit
		// 	}
		// }
	}
	return field.Limit
}

func computeDeltaUint64(s0 uint64, s1 uint64, max_value *uint64, limit *uint64) (uint64, string) {
	// s0 and s1 has value
	if s0 <= s1 {
		// increment value
		delta := s1 - s0
		if limit != nil {
			if delta > *limit {
				return delta, "overrate"
			} else {
				return delta, "normal"
			}
		} else {
			return delta, "normal"
		}
	} else {
		// overflow or counter was reset (device reboot)
		if s1 == 0 {
			// new value is 0
			return s1, "zero"
		}
		if max_value == nil {
			// max_value is not set --> assume counter was reset --> return s1
			return s1, "reset"
		} else {
			value := (*max_value - s0) + s1
			if limit != nil {
				if value > *limit {
					// value is above limit --> assume counter was reset --> return s1
					return s1, "reset"
				} else {
					// value is below limit --> assume counter overflow --> return value
					return value, "overflow"
				}
			} else {
				// limit is not set --> return "NIL"
				return 0, "limit-not-set"
			}
		}
	}
}

func computeDeltaInt64(s0 int64, s1 int64, max_value *int64, limit *int64) (int64, string) {
	// s0 and s1 has value
	if s0 <= s1 {
		// increment value
		delta := s1 - s0
		if limit != nil {
			if delta > *limit {
				return delta, "overrate"
			} else {
				return delta, "normal"
			}
		} else {
			return delta, "normal"
		}
	} else {
		// overflow or counter was reset (device reboot)
		if s1 == 0 {
			// new value is 0
			return s1, "zero"
		}
		if max_value == nil {
			// max_value is not set --> assume counter was reset --> return s1
			return s1, "reset"
		} else {
			value := (*max_value - s0) + s1
			if limit != nil {
				if value > *limit {
					// value is above limit --> assume counter was reset --> return s1
					return s1, "reset"
				} else {
					// value is below limit --> assume counter overflow --> return value
					return value, "overflow"
				}
			} else {
				// limit is not set --> return "NIL"
				return 0, "limit-not-set"
			}
		}
	}
}
