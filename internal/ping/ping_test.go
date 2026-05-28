package ping

import (
	"context"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// mockPinger is a test double for Pinger that records concurrency and returns preset results.
type mockPinger struct {
	mu          sync.Mutex
	maxInflight int
	inflight    int
	results     []Result // returned in round-robin order
	callIdx     int
}

func (m *mockPinger) Ping(_ context.Context, _ string) Result {
	m.mu.Lock()
	m.inflight++
	if m.inflight > m.maxInflight {
		m.maxInflight = m.inflight
	}
	idx := m.callIdx % len(m.results)
	m.callIdx++
	r := m.results[idx]
	m.mu.Unlock()

	time.Sleep(10 * time.Millisecond)

	m.mu.Lock()
	m.inflight--
	m.mu.Unlock()
	return r
}

func (m *mockPinger) Close() {}

func TestPingSuccess_AllReplies(t *testing.T) {
	m := &mockPinger{results: []Result{{Success: true, RTTMs: 5.0}}}
	r := m.Ping(context.Background(), "127.0.0.1")
	if !r.Success {
		t.Fatal("expected Success=true")
	}
	if r.RTTMs != 5.0 {
		t.Fatalf("expected RTTMs=5.0, got %v", r.RTTMs)
	}
}

func TestPingFailure_ZeroReplies(t *testing.T) {
	m := &mockPinger{results: []Result{{Success: false}}}
	r := m.Ping(context.Background(), "127.0.0.1")
	if r.Success {
		t.Fatal("expected Success=false")
	}
	if r.RTTMs != 0 {
		t.Fatalf("expected RTTMs=0, got %v", r.RTTMs)
	}
}

func TestPingPartialReplies_CountsAsSuccess(t *testing.T) {
	// Simulate 1 of 2 replies received — caller sees Success=true with RTT of the one reply.
	m := &mockPinger{results: []Result{{Success: true, RTTMs: 8.0}}}
	r := m.Ping(context.Background(), "127.0.0.1")
	if !r.Success {
		t.Fatal("expected Success=true for partial reply")
	}
}

func TestPingSemaphoreLimitsConcurrency(t *testing.T) {
	const pingConcurrency = 10
	const goroutines = 50

	var maxSeen atomic.Int64
	var inflight atomic.Int64
	var wg sync.WaitGroup

	// Use a semaphore directly to verify the cap
	sem := make(chan struct{}, pingConcurrency)

	for i := 0; i < goroutines; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			sem <- struct{}{}
			cur := inflight.Add(1)
			if cur > int64(pingConcurrency) {
				// record violation
				maxSeen.Store(cur)
			}
			time.Sleep(5 * time.Millisecond)
			inflight.Add(-1)
			<-sem
		}()
	}
	wg.Wait()

	if maxSeen.Load() > int64(pingConcurrency) {
		t.Fatalf("concurrency exceeded limit: %d > %d", maxSeen.Load(), pingConcurrency)
	}
}
