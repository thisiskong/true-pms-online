package device

import "context"

// DeviceRepository loads the device list from Postgres with a file-based fallback.
type DeviceRepository interface {
	LoadFromDB(ctx context.Context) ([]Device, error)
	LoadFromCache() ([]Device, error)
	SaveCache(devices []Device) error
}

// CompositeRepository tries Postgres first, then falls back to the local JSON cache.
type CompositeRepository struct {
	pg    *PostgresRepository
	cache *FileCache
}

func NewCompositeRepository(pg *PostgresRepository, cache *FileCache) *CompositeRepository {
	return &CompositeRepository{pg: pg, cache: cache}
}

// Load returns the device list from Postgres; on failure it falls back to cache.
// Returns (devices, fromCache bool, error).
func (r *CompositeRepository) Load(ctx context.Context) ([]Device, bool, error) {
	devices, err := r.pg.LoadFromDB(ctx)
	if err == nil {
		_ = r.cache.SaveCache(devices)
		return devices, false, nil
	}

	cached, cacheErr := r.cache.LoadFromCache()
	if cacheErr != nil {
		return nil, false, cacheErr
	}
	return cached, true, nil
}
