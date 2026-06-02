package event

import (
	"strings"
	"time"
)

const plainTimeFormat = "2006-01-02T15:04:05"

// LocalTime is a time.Time that marshals to/from JSON without a timezone suffix.
// Example: "2026-05-27T10:00:01"
type LocalTime struct {
	time.Time
}

func NewLocalTime(t time.Time) LocalTime {
	return LocalTime{t}
}

func (p LocalTime) MarshalJSON() ([]byte, error) {
	return []byte(`"` + p.UTC().Format(plainTimeFormat) + `"`), nil
}

func (p *LocalTime) UnmarshalJSON(data []byte) error {
	s := strings.Trim(string(data), `"`)
	t, err := time.ParseInLocation(plainTimeFormat, s, time.UTC)
	if err != nil {
		return err
	}
	p.Time = t
	return nil
}
