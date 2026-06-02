package device

// Device holds all connection parameters for a single SNMP target.
// v3-specific fields are empty string for v2c devices.
type Device struct {
	IP            string
	Name          string
	Port          uint16
	SNMPVersion   int    // 2 (v2c) or 3 (v3)
	Community     string // v2c only
	SecurityName  string // v3: USM username
	SecurityLevel string // v3: "noAuthNoPriv" | "authNoPriv" | "authPriv"
	AuthProtocol  string // v3: "MD5" | "SHA" | "SHA256"
	AuthKey       string // v3
	PrivProtocol  string // v3: "DES" | "AES" | "AES256"
	PrivKey       string // v3
}
