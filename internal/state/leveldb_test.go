package state

import (
	"testing"
	"time"
)

func openTestStore(t *testing.T) *LevelDBStore {
	t.Helper()
	store, err := NewLevelDBStore(t.TempDir())
	if err != nil {
		t.Fatalf("open store: %v", err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func TestLevelDB_RoundTrip(t *testing.T) {
	store := openTestStore(t)

	st := DeviceState{
		EngineProbed:        true,
		UseEngineOIDs:       true,
		LastEngineBoots:     42,
		LastEngineTime:      3600,
		ConsecutiveFailures: 2,
		LastBootTime:        time.Date(2026, 5, 27, 9, 0, 0, 0, time.UTC),
	}

	if err := store.Put("10.0.0.1", st); err != nil {
		t.Fatal(err)
	}

	got, err := store.Get("10.0.0.1")
	if err != nil {
		t.Fatal(err)
	}

	if got.LastEngineBoots != 42 || got.LastEngineTime != 3600 {
		t.Fatal("engine fields mismatch")
	}
	if got.ConsecutiveFailures != 2 {
		t.Fatal("ConsecutiveFailures mismatch")
	}
	if !got.LastBootTime.Equal(st.LastBootTime) {
		t.Fatal("LastBootTime mismatch")
	}
}

func TestLevelDB_MissingKey(t *testing.T) {
	store := openTestStore(t)
	st, err := store.Get("10.0.0.99")
	if err != nil {
		t.Fatal(err)
	}
	if st.EngineProbed || st.LastEngineBoots != 0 {
		t.Fatal("expected zero-value state for missing key")
	}
}

func TestLevelDB_Delete(t *testing.T) {
	store := openTestStore(t)
	_ = store.Put("10.0.0.1", DeviceState{LastEngineBoots: 1})
	if err := store.Delete("10.0.0.1"); err != nil {
		t.Fatal(err)
	}
	st, _ := store.Get("10.0.0.1")
	if st.LastEngineBoots != 0 {
		t.Fatal("expected zero state after delete")
	}
}

func TestLevelDB_Keys(t *testing.T) {
	store := openTestStore(t)
	_ = store.Put("10.0.0.1", DeviceState{})
	_ = store.Put("10.0.0.2", DeviceState{})
	keys, err := store.Keys()
	if err != nil {
		t.Fatal(err)
	}
	if len(keys) != 2 {
		t.Fatalf("expected 2 keys, got %d", len(keys))
	}
}
