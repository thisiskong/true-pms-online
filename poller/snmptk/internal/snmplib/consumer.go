package snmplib

import (
	"fmt"
	"log"
	"reflect"
	"sync"
	"time"

	"github.com/syndtr/goleveldb/leveldb"
)

func NewConsumer(setting *AppSetting, task *interface{}, deltaConfig *[]DeltaConfig,
	wg *sync.WaitGroup, db *leveldb.DB, tasksDone chan SnmpResult, size int) {
}

func save(db *DeltaDB, deltaConfig *[]DeltaConfig, pollint int, target *SnmpTarget, collectTime JsonTime, pollData map[string]*PollData, metric *IfTableMetric) *DeltaResult {
	if db == nil {
		// delta is disabled
		return nil
	}

	// ifTable
	ret := DeltaResult{
		IP:       target.IP,
		Hostname: target.Device,
		Entries:  make([]DeltaEntry, 0, len(pollData)),
	}
	for _, row := range pollData {
		if row.Index == "" {
			log.Printf("Error! %v|%v", target.IP, row.Index)
			metric.IntfErr.Inc()
			continue
		}

		intf, ok := target.Interfaces[row.Index]
		if !ok {
			// intf.poll is disabled
			continue
		}

		key := fmt.Sprintf("%s-%s", target.IP, row.Index)
		saved, err := db.GetValue([]byte(key))
		if err != nil {
			// NotFound --> New Interface: save new value, no delta value
			saved2 := newSavedValue(collectTime, row, deltaConfig)
			dberr := db.PutValue([]byte(key), saved2)
			if dberr != nil {
				log.Fatalf("Error! %v", dberr)
			}
		} else {
			// Found --> compute delta
			saved2 := newSavedValue(collectTime, row, deltaConfig)
			if saved.isExpired(saved2, pollint) {
				// expired data: save new value, do not emit delta
				db.PutValue([]byte(key), saved2)
				metric.IntfExpired.Inc()
				log.Printf("delta: %s [expired], t1 = %v, t2 = %v", key, saved.CollectTime.Format(DateTimeFormat), saved2.CollectTime.Format(DateTimeFormat))
				// delta := saved.computeDelta(&row, key, deltaConfig, saved2)
				// ret.Entries = append(ret.Entries, *delta)
			} else {
				// check if counter was reset
				if saved.isReset(saved2) {
					// ifCounterDiscontinuityTime changed
					// saved new value and do not emit delta
					db.PutValue([]byte(key), saved2)
					metric.IntfReset.Inc()
					log.Printf("delta: %s [intfReset]", key)

				} else {
					// ok: save new value and emit delta
					db.PutValue([]byte(key), saved2)
					delta := saved.computeDelta(target, intf, row, key, deltaConfig, saved2)
					ret.Entries = append(ret.Entries, *delta)

					for _, entry := range delta.Values {
						switch entry.Status {
						case "normal":
							metric.DeltaNormal++
						case "zero":
							metric.DeltaZero++
						case "reset":
							metric.DeltaReset++
						case "overflow":
							metric.DeltaOverflow++
						case "overrate":
							metric.DeltaOverrate++
						default:
							metric.DeltaErr++
						}
					}
					// log.Printf("delta: %s [ok]", key)
				}
			}
			// for _, deltaValue := range delta.Values {
			// 	log.Printf("[%v] {%v} %v", key, deltaValue.Status, deltaValue.Value)
			// }
		}
	}
	// log.Printf("ret = %v", ret)
	return &ret
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

func newSavedValue(collectTime JsonTime, row *PollData, deltaConfig *[]DeltaConfig) *SavedValue {
	saved := &SavedValue{CollectTime: time.Time(collectTime), Values: make(map[string]interface{})}
	for _, dtconfig := range *deltaConfig {
		val, ok := row.Values[dtconfig.Name]
		if ok && val != nil {
			if val.Value != nil {
				saved.Values[dtconfig.Name] = val.Value
			}
		}
	}
	return saved
}

func (saved1 *SavedValue) isExpired(saved2 *SavedValue, pollint int) bool {
	// data is consider expired if (saved1.CollectTime + (pollint * 2)) < saved2.CollectTime
	d := time.Duration(pollint*2) * time.Second
	return saved1.CollectTime.Add(d).Before(saved2.CollectTime)
}

func (saved1 *SavedValue) isReset(saved2 *SavedValue) bool {
	val1, ok1 := saved1.Values["ifCounterDiscontinuityTime"]
	val2, ok2 := saved2.Values["ifCounterDiscontinuityTime"]
	if ok1 && ok2 {
		return !(val1 == val2)
	}
	return false
}

func (saved1 *SavedValue) computeDelta(target *SnmpTarget, intf *Intf, row *PollData, key string, deltaConfig *[]DeltaConfig, saved2 *SavedValue) *DeltaEntry {
	meas := int(time.Time(saved2.CollectTime).Sub(time.Time(saved1.CollectTime)).Seconds())
	delta := DeltaEntry{
		CollectTime: JsonTime(saved1.CollectTime),
		Meas:        meas,
		Key:         key,
		IfIndex:     row.Index,
		Values:      make(map[string]*DeltaValue),
	}

	for _, dtconfig := range *deltaConfig {
		value1, ok1 := saved1.Values[dtconfig.Name]
		value2, ok2 := saved2.Values[dtconfig.Name]

		if ok1 && ok2 {
			type1 := reflect.TypeOf(value1)
			type2 := reflect.TypeOf(value2)
			if type1 == type2 {
				switch v := value1.(type) {
				case uint64:
					switch dtconfig.Mode {
					case "latest":
						delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "latest", Value1: value1, Value2: value2, Delta: value2}
					default:
						// mode = "delta" or empty
						limit := getLimit(row, &dtconfig, meas, intf)
						deltaVal, deltaFlag := computeDeltaUint64(value1.(uint64), value2.(uint64), dtconfig.Max, limit)
						delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: deltaFlag, Value1: value1, Value2: value2, Delta: deltaVal}
					}
				case int64:
					switch dtconfig.Mode {
					case "latest":
						delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "latest", Value1: value1, Value2: value2, Delta: value2}
					default:
						// mode = "delta" or empty
						var max_ptr *int64
						var limit_ptr *int64
						if dtconfig.Max != nil {
							max := int64(*dtconfig.Max)
							max_ptr = &max
						}
						if dtconfig.Limit != nil {
							limit := int64(*dtconfig.Limit)
							limit_ptr = &limit
						}
						deltaVal, deltaFlag := computeDeltaInt64(value1.(int64), value2.(int64), max_ptr, limit_ptr)
						delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: deltaFlag, Value1: value1, Value2: value2, Delta: deltaVal}
					}
				case string:
					// ignore "mode", always return latest value
					delta.Values[dtconfig.Name] = &DeltaValue{Name: dtconfig.Name, Status: "ok", Value1: value1, Value2: value2, Delta: value2.(string)}
				default:
					log.Printf("Error! %s, ifIndex=%s: ComputeDelta Not Support %v, %v, %v", target.IP, intf.Ifindex, v, type1, type2)
				}
			} else {
				// different type
				log.Printf("Error! %s, ifIndex=%s: Different Type: value1 = %v {%v}, value2 = %v {%v}", target.IP, intf.Ifindex, value1, type1, value2, type2)
			}

		} else if ok1 && !ok2 {
		} else if !ok1 && ok2 {
		}
	}
	return &delta
}

func getLimit(row *PollData, dtconfig *DeltaConfig, meas int, intf *Intf) *uint64 {
	if dtconfig.Name == "ifHCInOctets" || dtconfig.Name == "ifHCOutOctets" {
		// compute limit from wire speed and convert to octets
		// octets = meas x (ifspeed (bit-per-sec) / 8)
		limit := uint64(meas) * uint64(intf.Ifspeed) / 8
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
	return dtconfig.Limit
}
