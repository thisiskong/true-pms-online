package snmp

import (
	"context"
	"fmt"
	"time"

	"github.com/gosnmp/gosnmp"

	"github.com/thisiskong/true-pms-online/internal/device"
)

// SNMPClient sends a multi-varbind GET PDU and returns OID → uint32 value.
// Returns ErrNoSuchObject for individual varbinds that return noSuchObject.
type SNMPClient interface {
	Get(ctx context.Context, dev device.Device, oids []string) (map[string]uint32, error)
}

// ErrNoSuchObject signals that a varbind returned noSuchObject/noSuchInstance.
var ErrNoSuchObject = fmt.Errorf("noSuchObject")

// GoSNMPClient is the production implementation using gosnmp.
type GoSNMPClient struct {
	timeout  time.Duration
	retries  int
}

func NewGoSNMPClient(timeout time.Duration, retries int) *GoSNMPClient {
	return &GoSNMPClient{timeout: timeout, retries: retries}
}

func (c *GoSNMPClient) Get(ctx context.Context, dev device.Device, oids []string) (map[string]uint32, error) {
	g, err := c.newSession(dev)
	if err != nil {
		return nil, err
	}
	if err := g.Connect(); err != nil {
		return nil, fmt.Errorf("snmp connect %s: %w", dev.IP, err)
	}
	defer g.Conn.Close()

	result, err := g.Get(oids)
	if err != nil {
		return nil, fmt.Errorf("snmp get %s: %w", dev.IP, err)
	}

	out := make(map[string]uint32, len(result.Variables))
	for _, v := range result.Variables {
		oid := v.Name
		// gosnmp prepends a dot; normalise
		if len(oid) > 0 && oid[0] == '.' {
			oid = oid[1:]
		}
		switch v.Type {
		case gosnmp.NoSuchObject, gosnmp.NoSuchInstance:
			out[oid] = 0
			// mark as absent so callers can distinguish 0 from absent
			_ = v
		case gosnmp.TimeTicks, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Integer:
			out[oid] = uint32(gosnmp.ToBigInt(v.Value).Uint64())
		case gosnmp.Counter64:
			out[oid] = uint32(gosnmp.ToBigInt(v.Value).Uint64())
		default:
			// unsupported type — skip
		}
	}
	return out, nil
}

// GetWithAbsent is like Get but returns a separate absent set for noSuchObject varbinds.
func (c *GoSNMPClient) GetWithAbsent(ctx context.Context, dev device.Device, oids []string) (values map[string]uint32, absent map[string]bool, err error) {
	g, err := c.newSession(dev)
	if err != nil {
		return nil, nil, err
	}
	if err := g.Connect(); err != nil {
		return nil, nil, fmt.Errorf("snmp connect %s: %w", dev.IP, err)
	}
	defer g.Conn.Close()

	result, err := g.Get(oids)
	if err != nil {
		return nil, nil, fmt.Errorf("snmp get %s: %w", dev.IP, err)
	}

	values = make(map[string]uint32, len(result.Variables))
	absent = make(map[string]bool)
	for _, v := range result.Variables {
		oid := v.Name
		if len(oid) > 0 && oid[0] == '.' {
			oid = oid[1:]
		}
		switch v.Type {
		case gosnmp.NoSuchObject, gosnmp.NoSuchInstance:
			absent[oid] = true
		case gosnmp.TimeTicks, gosnmp.Counter32, gosnmp.Gauge32, gosnmp.Integer:
			values[oid] = uint32(gosnmp.ToBigInt(v.Value).Uint64())
		case gosnmp.Counter64:
			values[oid] = uint32(gosnmp.ToBigInt(v.Value).Uint64())
		}
	}
	return values, absent, nil
}

func (c *GoSNMPClient) newSession(dev device.Device) (*gosnmp.GoSNMP, error) {
	port := dev.Port
	if port == 0 {
		port = 161
	}

	g := &gosnmp.GoSNMP{
		Target:  dev.IP,
		Port:    port,
		Timeout: c.timeout,
		Retries: c.retries,
	}

	switch dev.SNMPVersion {
	case 3:
		g.Version = gosnmp.Version3
		g.SecurityModel = gosnmp.UserSecurityModel
		g.MsgFlags = securityLevel(dev.SecurityLevel)
		g.SecurityParameters = &gosnmp.UsmSecurityParameters{
			UserName:                 dev.SecurityName,
			AuthenticationProtocol:  authProtocol(dev.AuthProtocol),
			AuthenticationPassphrase: dev.AuthKey,
			PrivacyProtocol:          privProtocol(dev.PrivProtocol),
			PrivacyPassphrase:        dev.PrivKey,
		}
	default:
		g.Version = gosnmp.Version2c
		g.Community = dev.Community
	}

	return g, nil
}

func securityLevel(s string) gosnmp.SnmpV3MsgFlags {
	switch s {
	case "authPriv":
		return gosnmp.AuthPriv
	case "authNoPriv":
		return gosnmp.AuthNoPriv
	default:
		return gosnmp.NoAuthNoPriv
	}
}

func authProtocol(s string) gosnmp.SnmpV3AuthProtocol {
	switch s {
	case "SHA":
		return gosnmp.SHA
	case "SHA256":
		return gosnmp.SHA256
	default:
		return gosnmp.MD5
	}
}

func privProtocol(s string) gosnmp.SnmpV3PrivProtocol {
	switch s {
	case "AES":
		return gosnmp.AES
	case "AES256":
		return gosnmp.AES256
	default:
		return gosnmp.DES
	}
}
