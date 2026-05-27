package device

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5/pgxpool"
)

// PostgresRepository loads the device list from the device table.
type PostgresRepository struct {
	pool        *pgxpool.Pool
	defaultPort uint16
	query       string
}

func NewPostgresRepository(pool *pgxpool.Pool, defaultPort uint16, query string) *PostgresRepository {
	return &PostgresRepository{pool: pool, defaultPort: defaultPort, query: query}
}

func (r *PostgresRepository) LoadFromDB(ctx context.Context) ([]Device, error) {
	rows, err := r.pool.Query(ctx, r.query)
	if err != nil {
		return nil, fmt.Errorf("query devices: %w", err)
	}
	defer rows.Close()

	var devices []Device
	for rows.Next() {
		var d Device
		var port int
		var version int
		if err := rows.Scan(
			&d.IP, &d.Name, &port, &version,
			&d.Community, &d.SecurityName, &d.SecurityLevel,
			&d.AuthProtocol, &d.AuthKey, &d.PrivProtocol, &d.PrivKey,
		); err != nil {
			return nil, fmt.Errorf("scan device row: %w", err)
		}
		d.Port = uint16(port)
		if d.Port == 0 {
			d.Port = r.defaultPort
		}
		d.SNMPVersion = version
		if d.SNMPVersion == 0 {
			d.SNMPVersion = 2
		}
		devices = append(devices, d)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate device rows: %w", err)
	}
	return devices, nil
}
