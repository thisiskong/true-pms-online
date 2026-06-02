package device

import (
	"os"
	"path/filepath"
	"testing"
)

func TestFileCache_RoundTrip(t *testing.T) {
	dir := t.TempDir()
	cache := NewFileCache(filepath.Join(dir, "devices.json"))

	devices := []Device{
		{IP: "10.0.0.1", Name: "sw-01", Port: 161, SNMPVersion: 2, Community: "public"},
		{IP: "10.0.0.2", Name: "sw-02", Port: 161, SNMPVersion: 2, Community: "public"},
	}

	if err := cache.SaveCache(devices); err != nil {
		t.Fatal(err)
	}

	loaded, err := cache.LoadFromCache()
	if err != nil {
		t.Fatal(err)
	}
	if len(loaded) != len(devices) {
		t.Fatalf("expected %d devices, got %d", len(devices), len(loaded))
	}
	if loaded[0].IP != devices[0].IP || loaded[1].Name != devices[1].Name {
		t.Fatal("device data mismatch")
	}
}

func TestFileCache_LoadMissing(t *testing.T) {
	dir := t.TempDir()
	cache := NewFileCache(filepath.Join(dir, "nonexistent.json"))
	_, err := cache.LoadFromCache()
	if err == nil {
		t.Fatal("expected error for missing cache file")
	}
}

func TestFileCache_Atomic(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "devices.json")
	cache := NewFileCache(path)

	_ = cache.SaveCache([]Device{{IP: "10.0.0.1", Name: "sw"}})

	// Ensure no .tmp file is left behind
	if _, err := os.Stat(path + ".tmp"); !os.IsNotExist(err) {
		t.Fatal("tmp file should be removed after save")
	}
}
