package device

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// FileCache persists the device list as a JSON file for offline fallback.
type FileCache struct {
	path string
}

func NewFileCache(path string) *FileCache {
	return &FileCache{path: path}
}

func (c *FileCache) LoadFromCache() ([]Device, error) {
	data, err := os.ReadFile(c.path)
	if err != nil {
		return nil, fmt.Errorf("read device cache %s: %w", c.path, err)
	}
	var devices []Device
	if err := json.Unmarshal(data, &devices); err != nil {
		return nil, fmt.Errorf("parse device cache: %w", err)
	}
	return devices, nil
}

func (c *FileCache) SaveCache(devices []Device) error {
	if err := os.MkdirAll(filepath.Dir(c.path), 0755); err != nil {
		return fmt.Errorf("create cache dir: %w", err)
	}
	data, err := json.Marshal(devices)
	if err != nil {
		return fmt.Errorf("marshal device cache: %w", err)
	}
	tmp := c.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0644); err != nil {
		return fmt.Errorf("write device cache tmp: %w", err)
	}
	return os.Rename(tmp, c.path)
}
