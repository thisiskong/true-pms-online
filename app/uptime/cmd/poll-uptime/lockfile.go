package main

import (
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

func acquireLock(path string, log *slog.Logger) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return fmt.Errorf("create lock dir: %w", err)
	}

	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("read lock file: %w", err)
	}

	if err == nil {
		pidStr := strings.TrimSpace(string(data))
		if pid, parseErr := strconv.Atoi(pidStr); parseErr == nil {
			if isProcessAlive(pid) {
				return fmt.Errorf("another instance is running (pid %d)", pid)
			}
			log.Warn("stale lock file found, overwriting", "dead_pid", pid)
		}
	}

	return os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0644)
}

func releaseLock(path string) {
	_ = os.Remove(path)
}

func isProcessAlive(pid int) bool {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	err = proc.Signal(syscall.Signal(0))
	return err == nil
}
