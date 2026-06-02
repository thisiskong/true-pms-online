package snmplib2

import (
	"bytes"
	"encoding/gob"
	"log"
	"path/filepath"
	"sync"
	"time"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/filter"
	"github.com/syndtr/goleveldb/leveldb/opt"
)

type DeltaDB struct {
	dbpath string
	db     *leveldb.DB
}

type SavedValue struct {
	CollectTime time.Time
	Values      map[string]interface{}
}

func (saved1 *SavedValue) isExpired(saved2 *SavedValue, pollint int, expiredMultipler int) bool {
	// data is consider expired if (saved1.CollectTime + (pollint * 2)) < saved2.CollectTime
	// d := time.Duration(pollint*2) * time.Second
	d := time.Duration(pollint*expiredMultipler) * time.Second
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

func NewLevelDB(dbpath string, timeout time.Duration) (*DeltaDB, error) {
	// timeout = 0 --> do not retry, return immediately if failed
	// timeout > 0 --> keep retry until timeout
	t := time.Now()
	var err error
	var db *leveldb.DB
	for true {
		db, err = leveldb.OpenFile(dbpath, &opt.Options{Filter: filter.NewBloomFilter(10)})
		if err == nil {
			// successful
			return &DeltaDB{dbpath: dbpath, db: db}, nil
		} else {
			filepath, _ := filepath.Abs(dbpath)
			log.Printf("Error! Failed to open leveldb: %s [%v]", filepath, err)

			// timeout > 0 && timeout is not reached
			if timeout.Seconds() > 0 {
				if time.Since(t) < timeout {
					// retry after 5 seconds
					log.Printf("Warn! leveldb will retry after 5 seconds...")
					time.Sleep(time.Duration(5) * time.Second)
					continue
				} else {
					log.Printf("Error! leveldb timeout")
				}
			}
			return nil, err
			// // probably db corrupted, delete dbpath and reset
			// err = os.RemoveAll(dbpath)
			// if err != nil {
			// 	// unable to delete dbpath, return error
			// 	log.Printf("Error! Failed to delete leveldb: %s [%v]", filepath, err)
			// 	return nil, err
			// }
			// // open db for 2nd time
			// db, err = leveldb.OpenFile(dbpath, &opt.Options{Filter: filter.NewBloomFilter(10)})
			// if err == nil {
			// 	return &DeltaDB{dbpath: dbpath, db: db}, nil
			// }
			// log.Printf("Error! Failed to open leveldb: %s [%v]", filepath, err)
			// return nil, err
		}
	}
	return nil, nil
}

func (deltadb *DeltaDB) PutValue(key []byte, value *SavedValue) error {
	var buf bytes.Buffer
	enc := gob.NewEncoder(&buf)
	enc.Encode(value)
	err := deltadb.db.Put(key, buf.Bytes(), nil)
	return err
}

func (deltadb *DeltaDB) GetValue(key []byte) (*SavedValue, error) {
	data, err := deltadb.db.Get(key, nil)
	if err != nil {
		return nil, err
	}
	dec := gob.NewDecoder(bytes.NewReader(data))
	var value SavedValue
	err = dec.Decode(&value)
	return &value, err
}

func (deltadb *DeltaDB) Cleanup(tstamp time.Time, wg *sync.WaitGroup) {
	defer wg.Done()
	cnt := 0
	cnt_err := 0
	cnt_expired := 0
	var saved SavedValue
	t := time.Now()

	// batch write
	batch := new(leveldb.Batch)
	iter := deltadb.db.NewIterator(nil, nil)
	for iter.Next() {
		cnt += 1
		dec := gob.NewDecoder(bytes.NewReader(iter.Value()))
		err := dec.Decode(&saved)
		if err != nil {
			// failed to decode, so we will remove corrupted record
			batch.Delete(iter.Key())
			// err = deltadb.db.Delete(iter.Key(), nil)
			// if err != nil {
			// 	log.Printf("Error! delete1 %v", err)
			// }
			cnt_err += 1
		} else {
			if saved.CollectTime.Before(tstamp) {
				// expired record
				batch.Delete(iter.Key())
				// err = deltadb.db.Delete(iter.Key(), nil)
				// if err != nil {
				// 	log.Printf("Error! %v", err)
				// }
				cnt_expired += 1
			}
		}
	}
	iter.Release()
	err := iter.Error()
	if err != nil {
		log.Printf("Error! iter.release %v", err)
	}

	// execute batch
	err = deltadb.db.Write(batch, nil)
	if err != nil {
		log.Printf("Error! batch.write %v", err)
	}
	log.Printf("LevelDB.Cleanup has %d entries, %d err, %d expired in %v", cnt, cnt_err, cnt_expired, time.Since(t))
}
