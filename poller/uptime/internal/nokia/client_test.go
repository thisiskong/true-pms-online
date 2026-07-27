package nokia

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func newTestClient(t *testing.T, handler http.HandlerFunc) (*Client, *int32) {
	t.Helper()
	var loginCount int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/auth/login") {
			atomic.AddInt32(&loginCount, 1)
		}
		handler(w, r)
	}))
	t.Cleanup(srv.Close)

	c := NewClient(Config{
		BaseURL:     srv.URL,
		Username:    "adminuser",
		Password:    "password",
		Timeout:     5 * time.Second,
		Concurrency: 10,
	})
	return c, &loginCount
}

func writeJSON(w http.ResponseWriter, body string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(body))
}

func TestGetUptime_ParsesSysUptimeAndBootDatetime(t *testing.T) {
	c, _ := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/auth/login"):
			writeJSON(w, `{"accessToken":"tok-1"}`)
		case strings.HasSuffix(r.URL.Path, "sys-up-time"):
			if got := r.Header.Get("Authorization"); got != "Bearer tok-1" {
				t.Errorf("unexpected auth header: %q", got)
			}
			writeJSON(w, `{"nokia-ietf-system-aug:sys-up-time":"2761345900"}`)
		case strings.HasSuffix(r.URL.Path, "boot-datetime"):
			writeJSON(w, `{"ietf-system:boot-datetime":"2026-06-26T01:08:53+07:00"}`)
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	})

	sysUp, boot, err := c.GetUptime(context.Background(), "RET05008G00")
	if err != nil {
		t.Fatalf("GetUptime: %v", err)
	}
	if sysUp != 2761345900 {
		t.Errorf("sysUpTime = %d, want 2761345900", sysUp)
	}
	wantBoot := time.Date(2026, 6, 26, 1, 8, 53, 0, time.FixedZone("", 7*3600))
	if !boot.Equal(wantBoot) {
		t.Errorf("bootTime = %v, want %v", boot, wantBoot)
	}
}

func TestGetUptime_ReusesTokenAcrossCalls(t *testing.T) {
	c, loginCount := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/auth/login"):
			writeJSON(w, `{"accessToken":"tok-1"}`)
		case strings.HasSuffix(r.URL.Path, "sys-up-time"):
			writeJSON(w, `{"nokia-ietf-system-aug:sys-up-time":"100"}`)
		case strings.HasSuffix(r.URL.Path, "boot-datetime"):
			writeJSON(w, `{"ietf-system:boot-datetime":"2026-06-26T01:08:53+07:00"}`)
		}
	})

	for i := 0; i < 5; i++ {
		if _, _, err := c.GetUptime(context.Background(), "DEV01"); err != nil {
			t.Fatalf("GetUptime call %d: %v", i, err)
		}
	}
	if got := int(atomic.LoadInt32(loginCount)); got != 1 {
		t.Errorf("login called %d times, want 1", got)
	}
}

func TestGetUptime_RelogsOn401(t *testing.T) {
	var tokenSeq int32
	var sysUpCalls int32
	c, loginCount := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/auth/login"):
			n := atomic.AddInt32(&tokenSeq, 1)
			writeJSON(w, fmt.Sprintf(`{"accessToken":"tok-%d"}`, n))
		case strings.HasSuffix(r.URL.Path, "sys-up-time"):
			n := atomic.AddInt32(&sysUpCalls, 1)
			if n == 1 {
				// First token is treated as stale by the server.
				w.WriteHeader(http.StatusUnauthorized)
				return
			}
			writeJSON(w, `{"nokia-ietf-system-aug:sys-up-time":"500"}`)
		case strings.HasSuffix(r.URL.Path, "boot-datetime"):
			writeJSON(w, `{"ietf-system:boot-datetime":"2026-06-26T01:08:53+07:00"}`)
		}
	})

	sysUp, _, err := c.GetUptime(context.Background(), "DEV01")
	if err != nil {
		t.Fatalf("GetUptime: %v", err)
	}
	if sysUp != 500 {
		t.Errorf("sysUpTime = %d, want 500", sysUp)
	}
	if got := int(atomic.LoadInt32(loginCount)); got != 2 {
		t.Errorf("login called %d times, want 2 (initial + relogin after 401)", got)
	}
}

func TestGetUptime_ConcurrencyCapped(t *testing.T) {
	var inFlight int32
	var maxInFlight int32
	var mu sync.Mutex

	c, _ := newTestClient(t, func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "/auth/login"):
			writeJSON(w, `{"accessToken":"tok-1"}`)
		case strings.HasSuffix(r.URL.Path, "sys-up-time"), strings.HasSuffix(r.URL.Path, "boot-datetime"):
			n := atomic.AddInt32(&inFlight, 1)
			mu.Lock()
			if n > maxInFlight {
				maxInFlight = n
			}
			mu.Unlock()
			time.Sleep(20 * time.Millisecond)
			atomic.AddInt32(&inFlight, -1)
			if strings.HasSuffix(r.URL.Path, "sys-up-time") {
				writeJSON(w, `{"nokia-ietf-system-aug:sys-up-time":"100"}`)
			} else {
				writeJSON(w, `{"ietf-system:boot-datetime":"2026-06-26T01:08:53+07:00"}`)
			}
		}
	})
	c.sem = make(chan struct{}, 3)

	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			_, _, _ = c.GetUptime(context.Background(), fmt.Sprintf("DEV%02d", n))
		}(i)
	}
	wg.Wait()

	mu.Lock()
	defer mu.Unlock()
	if maxInFlight > 3 {
		t.Errorf("max concurrent requests = %d, want <= 3", maxInFlight)
	}
}
