package event

import "context"

// EventEmitter receives reboot events for output (log file, Postgres, etc.).
type EventEmitter interface {
	Emit(ctx context.Context, ev RebootEvent) error
	Close() error
}

// MultiEmitter fans a single Emit call out to all configured emitters.
type MultiEmitter struct {
	emitters []EventEmitter
}

func NewMultiEmitter(emitters ...EventEmitter) *MultiEmitter {
	return &MultiEmitter{emitters: emitters}
}

func (m *MultiEmitter) Emit(ctx context.Context, ev RebootEvent) error {
	var last error
	for _, e := range m.emitters {
		if err := e.Emit(ctx, ev); err != nil {
			last = err
		}
	}
	return last
}

func (m *MultiEmitter) Close() error {
	var last error
	for _, e := range m.emitters {
		if err := e.Close(); err != nil {
			last = err
		}
	}
	return last
}
