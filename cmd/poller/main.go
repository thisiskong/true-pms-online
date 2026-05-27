package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/thisiskong/true-pms-online/internal/config"
	"github.com/thisiskong/true-pms-online/internal/device"
	"github.com/thisiskong/true-pms-online/internal/event"
	"github.com/thisiskong/true-pms-online/internal/metrics"
	"github.com/thisiskong/true-pms-online/internal/poller"
	"github.com/thisiskong/true-pms-online/internal/snmp"
	"github.com/thisiskong/true-pms-online/internal/state"
)

func main() {
	cfgFile := flag.String("config", "", "path to config.yaml")
	flag.Parse()

	cfg, err := config.Load(*cfgFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "load config: %v\n", err)
		os.Exit(1)
	}

	log := buildLogger(cfg.LogLevel)

	// PID lock — prevent overlapping cron runs
	if err := acquireLock(cfg.LockFile, log); err != nil {
		log.Error("acquire lock failed", "err", err)
		os.Exit(1)
	}
	defer releaseLock(cfg.LockFile)

	// Handle SIGTERM/SIGINT gracefully
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	// 14-minute hard deadline for the full cycle
	ctx, cancel := context.WithTimeout(ctx, 14*time.Minute)
	defer cancel()

	if err := run(ctx, cfg, log); err != nil {
		log.Error("run failed", "err", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, cfg *config.Config, log *slog.Logger) error {
	// Prune old log files
	event.PruneOldLogs(cfg.PollLogDir, cfg.RebootLogDir, cfg.LogRetentionDays, time.Now())

	// Open LevelDB
	store, err := state.NewLevelDBStore(cfg.LevelDBPath)
	if err != nil {
		return fmt.Errorf("open leveldb: %w", err)
	}
	defer store.Close()

	// Open Postgres (optional)
	var pool *pgxpool.Pool
	if cfg.PostgresDSN != "" {
		pgCtx, pgCancel := context.WithTimeout(ctx, cfg.PostgresTimeout)
		defer pgCancel()
		pool, err = pgxpool.New(pgCtx, cfg.PostgresDSN)
		if err != nil {
			log.Warn("postgres connect failed, continuing without DB", "err", err)
			pool = nil
		} else if err := pool.Ping(pgCtx); err != nil {
			log.Warn("postgres ping failed, continuing without DB", "err", err)
			pool.Close()
			pool = nil
		}
	}
	if pool != nil {
		defer pool.Close()
	}

	// Load devices
	devices, err := loadDevices(ctx, cfg, pool, log)
	if err != nil {
		return fmt.Errorf("load devices: %w", err)
	}
	if len(devices) == 0 {
		log.Warn("no devices loaded, exiting")
		return nil
	}
	log.Info("devices loaded", "count", len(devices))

	// Prune removed devices from state store
	if cfg.PruneRemovedDevices {
		pruneRemovedDevices(store, devices, log)
	}

	// Build emitters
	retryQueue := event.NewRetryQueue(cfg.PGRetryQueueFile, log)
	emitters := []event.EventEmitter{event.NewLogEmitter(log)}

	rebootLog, err := event.NewRebootLogEmitter(cfg.RebootLogDir)
	if err != nil {
		return fmt.Errorf("open reboot log: %w", err)
	}
	defer rebootLog.Close()
	emitters = append(emitters, rebootLog)

	var pgEmitter *event.PostgresEmitter
	if pool != nil && cfg.RebootPGTable != "" {
		pgEmitter = event.NewPostgresEmitter(pool, cfg.RebootPGTable, cfg.RebootPGTimeout, retryQueue, log)
		emitters = append(emitters, pgEmitter)
		// Drain retry queue before poll cycle
		if err := pgEmitter.DrainRetryQueue(ctx); err != nil {
			log.Warn("drain reboot retry queue", "err", err)
		}
	}

	emitter := event.NewMultiEmitter(emitters...)
	defer emitter.Close()

	// Poll log
	pollLog, err := event.NewFilePollLogger(cfg.PollLogDir)
	if err != nil {
		return fmt.Errorf("open poll log: %w", err)
	}
	defer pollLog.Close()

	// Uptime upsert
	var upsertFn poller.UpsertFunc
	if pool != nil && cfg.UptimePGTable != "" {
		uptimeUpsert := event.NewUptimeUpsert(pool, cfg.UptimeBatchSize, cfg.PGUptimeRetryQueueFile, log)
		uptimeUpsert.DrainRetryQueue(ctx)
		upsertFn = uptimeUpsert.UpsertAll
	}

	// SNMP client
	snmpClient := snmp.NewGoSNMPClient(cfg.SNMPTimeout, cfg.SNMPRetries)

	// Run poll cycle
	workerCfg := poller.WorkerConfig{
		Concurrency: cfg.Concurrency,
		SNMPTimeout: cfg.SNMPTimeout,
	}
	detectCfg := poller.DetectConfig{
		RolloverThresholdSeconds:  cfg.RolloverThresholdSeconds,
		MaxValueStreakThreshold:   cfg.MaxValueStreakThreshold,
		GapRebootThresholdSeconds: cfg.GapRebootThresholdSeconds,
	}

	cycleStart := time.Now()
	stats := poller.RunPollCycle(
		ctx, devices, store, snmpClient, emitter, pollLog, upsertFn,
		workerCfg, detectCfg, cfg.MaxConsecutiveFailures, log,
	)

	log.Info("poll cycle complete",
		"total", stats.Total,
		"success", stats.Success,
		"errors", stats.Errors,
		"reboots", stats.Reboots,
		"duration", stats.Duration,
	)

	// Push Prometheus metrics
	if err := metrics.Push(cfg.PushgatewayURL, cfg.PushgatewayJob, metrics.CycleMetrics{
		DevicesTotal: stats.Total,
		SuccessTotal: stats.Success,
		ErrorTotal:   stats.Errors,
		RebootTotal:  stats.Reboots,
		DurationSecs: time.Since(cycleStart).Seconds(),
		CompletedAt:  time.Now(),
	}); err != nil {
		log.Warn("metrics push failed", "err", err)
	}

	return nil
}

func loadDevices(ctx context.Context, cfg *config.Config, pool *pgxpool.Pool, log *slog.Logger) ([]device.Device, error) {
	cache := device.NewFileCache(cfg.DeviceCacheFile)

	if pool != nil {
		dbCtx, cancel := context.WithTimeout(ctx, cfg.PostgresTimeout)
		defer cancel()
		pg := device.NewPostgresRepository(pool, cfg.DefaultPort, cfg.DeviceQuery)
		repo := device.NewCompositeRepository(pg, cache)
		devices, fromCache, err := repo.Load(dbCtx)
		if err != nil {
			return nil, err
		}
		if fromCache {
			log.Warn("using cached device list (postgres unavailable)")
		}
		return devices, nil
	}

	// No Postgres — try cache only
	devices, err := cache.LoadFromCache()
	if err != nil {
		return nil, fmt.Errorf("no postgres and no cache: %w", err)
	}
	log.Warn("no postgres configured, using device cache")
	return devices, nil
}

func pruneRemovedDevices(store state.StateStore, devices []device.Device, log *slog.Logger) {
	known := make(map[string]bool, len(devices))
	for _, d := range devices {
		known[d.IP] = true
	}
	keys, err := store.Keys()
	if err != nil {
		log.Warn("list state keys for pruning", "err", err)
		return
	}
	for _, k := range keys {
		if !known[k] {
			if err := store.Delete(k); err != nil {
				log.Warn("delete stale state", "ip", k, "err", err)
			} else {
				log.Info("pruned removed device", "ip", k)
			}
		}
	}
}

func buildLogger(level string) *slog.Logger {
	var l slog.Level
	switch level {
	case "debug":
		l = slog.LevelDebug
	case "warn":
		l = slog.LevelWarn
	case "error":
		l = slog.LevelError
	default:
		l = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: l}))
}
