package state

// StateStore persists per-device polling state.
type StateStore interface {
	Get(ip string) (DeviceState, error)
	Put(ip string, state DeviceState) error
	Delete(ip string) error
	Keys() ([]string, error)
	Close() error
}
