package ping

import (
	"context"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/net/icmp"
	"golang.org/x/net/ipv4"
)

const payloadSize = 56

// Result holds the outcome of a single Ping call.
type Result struct {
	Success bool
	RTTMs   float64 // average RTT of received replies in ms; 0 when Success=false
}

// Pinger sends ICMP echo requests and reports reachability + latency.
type Pinger interface {
	Ping(ctx context.Context, ip string) Result
	Close()
}

// ICMPPinger implements Pinger using a shared raw ICMP socket.
// A background goroutine routes all incoming echo replies to waiting Ping calls.
// A semaphore limits simultaneous in-flight pings.
type ICMPPinger struct {
	conn    *icmp.PacketConn
	id      uint16 // fixed per process = PID & 0xffff
	nextSeq atomic.Uint32
	sem     chan struct{}
	timeout time.Duration
	count   int
	writeMu sync.Mutex

	mu      sync.Mutex
	waiters map[uint16]chan time.Time // seq → receive-time channel
}

// NewICMPPinger opens a raw ICMP socket. Requires CAP_NET_RAW (root on Linux).
func NewICMPPinger(timeout time.Duration, count, concurrency int) (*ICMPPinger, error) {
	conn, err := icmp.ListenPacket("ip4:icmp", "0.0.0.0")
	if err != nil {
		return nil, err
	}
	p := &ICMPPinger{
		conn:    conn,
		id:      uint16(os.Getpid() & 0xffff),
		sem:     make(chan struct{}, concurrency),
		timeout: timeout,
		count:   count,
		waiters: make(map[uint16]chan time.Time),
	}
	go p.readLoop()
	return p, nil
}

func (p *ICMPPinger) Close() {
	p.conn.Close()
}

// readLoop reads all incoming ICMP echo replies and dispatches to waiting Ping calls.
func (p *ICMPPinger) readLoop() {
	buf := make([]byte, 1500)
	for {
		_ = p.conn.SetReadDeadline(time.Now().Add(5 * time.Second))
		n, _, err := p.conn.ReadFrom(buf)
		if err != nil {
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
				continue
			}
			return
		}
		msg, err := icmp.ParseMessage(ipv4.ICMPTypeEchoReply.Protocol(), buf[:n])
		if err != nil {
			continue
		}
		echo, ok := msg.Body.(*icmp.Echo)
		if !ok || uint16(echo.ID) != p.id {
			continue
		}
		seq := uint16(echo.Seq)
		recvAt := time.Now()
		p.mu.Lock()
		ch, ok := p.waiters[seq]
		p.mu.Unlock()
		if ok {
			select {
			case ch <- recvAt:
			default:
			}
		}
	}
}

// Ping sends count ICMP echo requests to ip and waits for replies within timeout.
// Success is true if at least one reply is received. RTTMs is the average of received replies.
func (p *ICMPPinger) Ping(ctx context.Context, ip string) Result {
	select {
	case p.sem <- struct{}{}:
	case <-ctx.Done():
		return Result{}
	}
	defer func() { <-p.sem }()

	dst, err := net.ResolveIPAddr("ip4", ip)
	if err != nil {
		return Result{}
	}

	type seqEntry struct {
		seq    uint16
		sentAt time.Time
		ch     chan time.Time
	}

	entries := make([]seqEntry, p.count)
	for i := range entries {
		seq := uint16(p.nextSeq.Add(1) & 0xffff)
		ch := make(chan time.Time, 1)
		p.mu.Lock()
		p.waiters[seq] = ch
		p.mu.Unlock()
		entries[i] = seqEntry{seq: seq, ch: ch}
	}
	defer func() {
		p.mu.Lock()
		for _, e := range entries {
			delete(p.waiters, e.seq)
		}
		p.mu.Unlock()
	}()

	payload := make([]byte, payloadSize)

	for i := range entries {
		msg := &icmp.Message{
			Type: ipv4.ICMPTypeEcho,
			Code: 0,
			Body: &icmp.Echo{
				ID:   int(p.id),
				Seq:  int(entries[i].seq),
				Data: payload,
			},
		}
		b, err := msg.Marshal(nil)
		if err != nil {
			continue
		}
		entries[i].sentAt = time.Now()
		p.writeMu.Lock()
		_, _ = p.conn.WriteTo(b, dst)
		p.writeMu.Unlock()
	}

	// Fan-in: each entry's goroutine waits for its reply and forwards to replyCh.
	type replyItem struct{ rtt float64 }
	replyCh := make(chan replyItem, p.count)
	deadline := time.Now().Add(p.timeout)

	for _, e := range entries {
		go func(e seqEntry) {
			remaining := time.Until(deadline)
			if remaining <= 0 {
				return
			}
			t := time.NewTimer(remaining)
			defer t.Stop()
			select {
			case recvAt := <-e.ch:
				rtt := recvAt.Sub(e.sentAt).Seconds() * 1000
				replyCh <- replyItem{rtt: rtt}
			case <-t.C:
			case <-ctx.Done():
			}
		}(e)
	}

	var rtts []float64
	timer := time.NewTimer(p.timeout)
	defer timer.Stop()

COLLECT:
	for range entries {
		select {
		case r := <-replyCh:
			rtts = append(rtts, r.rtt)
		case <-timer.C:
			break COLLECT
		case <-ctx.Done():
			break COLLECT
		}
	}

	if len(rtts) == 0 {
		return Result{Success: false}
	}
	var sum float64
	for _, r := range rtts {
		sum += r
	}
	return Result{Success: true, RTTMs: sum / float64(len(rtts))}
}
