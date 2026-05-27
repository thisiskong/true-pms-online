package state

import (
	"encoding/json"
	"errors"
	"fmt"

	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/util"
)

// LevelDBStore implements StateStore using LevelDB.
type LevelDBStore struct {
	db *leveldb.DB
}

func NewLevelDBStore(path string) (*LevelDBStore, error) {
	db, err := leveldb.OpenFile(path, nil)
	if err != nil {
		return nil, fmt.Errorf("open leveldb %s: %w", path, err)
	}
	return &LevelDBStore{db: db}, nil
}

func (s *LevelDBStore) Get(ip string) (DeviceState, error) {
	data, err := s.db.Get([]byte(ip), nil)
	if errors.Is(err, leveldb.ErrNotFound) {
		return DeviceState{}, nil
	}
	if err != nil {
		return DeviceState{}, fmt.Errorf("leveldb get %s: %w", ip, err)
	}
	var st DeviceState
	if err := json.Unmarshal(data, &st); err != nil {
		return DeviceState{}, fmt.Errorf("unmarshal state %s: %w", ip, err)
	}
	return st, nil
}

func (s *LevelDBStore) Put(ip string, st DeviceState) error {
	data, err := json.Marshal(st)
	if err != nil {
		return fmt.Errorf("marshal state %s: %w", ip, err)
	}
	if err := s.db.Put([]byte(ip), data, nil); err != nil {
		return fmt.Errorf("leveldb put %s: %w", ip, err)
	}
	return nil
}

func (s *LevelDBStore) Delete(ip string) error {
	if err := s.db.Delete([]byte(ip), nil); err != nil {
		return fmt.Errorf("leveldb delete %s: %w", ip, err)
	}
	return nil
}

func (s *LevelDBStore) Keys() ([]string, error) {
	iter := s.db.NewIterator(&util.Range{}, nil)
	defer iter.Release()
	var keys []string
	for iter.Next() {
		keys = append(keys, string(iter.Key()))
	}
	return keys, iter.Error()
}

func (s *LevelDBStore) Close() error {
	return s.db.Close()
}
