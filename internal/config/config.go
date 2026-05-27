package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

type Config struct {
	Concurrency   int           `mapstructure:"concurrency"`
	SNMPTimeout   time.Duration `mapstructure:"snmp_timeout"`
	SNMPRetries   int           `mapstructure:"snmp_retries"`
	LockFile      string        `mapstructure:"lock_file"`
	LevelDBPath   string        `mapstructure:"leveldb_path"`
	DeviceCacheFile string      `mapstructure:"device_cache_file"`

	PollLogDir      string `mapstructure:"poll_log_dir"`
	RebootLogDir    string `mapstructure:"reboot_log_dir"`
	LogRetentionDays int   `mapstructure:"log_retention_days"`
	LogLevel        string `mapstructure:"log_level"`

	PostgresDSN     string        `mapstructure:"postgres_dsn"`
	PostgresTimeout time.Duration `mapstructure:"postgres_timeout"`

	RebootPGTable    string        `mapstructure:"reboot_pg_table"`
	RebootPGTimeout  time.Duration `mapstructure:"reboot_pg_timeout"`
	PGRetryQueueFile string        `mapstructure:"pg_retry_queue_file"`

	UptimePGTable          string `mapstructure:"uptime_pg_table"`
	UptimeBatchSize        int    `mapstructure:"uptime_batch_size"`
	PGUptimeRetryQueueFile string `mapstructure:"pg_uptime_retry_queue_file"`

	RolloverThresholdSeconds int `mapstructure:"rollover_threshold_seconds"`
	MaxValueStreakThreshold  int `mapstructure:"max_value_streak_threshold"`
	MaxConsecutiveFailures   int `mapstructure:"max_consecutive_failures"`
	GapRebootThresholdSeconds int `mapstructure:"gap_reboot_threshold_seconds"`

	PruneRemovedDevices bool   `mapstructure:"prune_removed_devices"`
	DefaultPort         uint16 `mapstructure:"default_port"`

	PushgatewayURL string `mapstructure:"pushgateway_url"`
	PushgatewayJob string `mapstructure:"pushgateway_job"`
}

func Load(cfgFile string) (*Config, error) {
	v := viper.New()

	v.SetDefault("concurrency", 500)
	v.SetDefault("snmp_timeout", "5s")
	v.SetDefault("snmp_retries", 1)
	v.SetDefault("lock_file", "/var/run/pms-poller.lock")
	v.SetDefault("leveldb_path", "./data/state.db")
	v.SetDefault("device_cache_file", "./data/devices.json")
	v.SetDefault("poll_log_dir", "./logs")
	v.SetDefault("reboot_log_dir", "./logs")
	v.SetDefault("log_retention_days", 30)
	v.SetDefault("log_level", "info")
	v.SetDefault("postgres_timeout", "10s")
	v.SetDefault("reboot_pg_timeout", "3s")
	v.SetDefault("pg_retry_queue_file", "./data/pg_retry.queue")
	v.SetDefault("uptime_pg_table", "device_last_uptime")
	v.SetDefault("uptime_batch_size", 500)
	v.SetDefault("pg_uptime_retry_queue_file", "./data/pg_uptime_retry.queue")
	v.SetDefault("rollover_threshold_seconds", 42520176)
	v.SetDefault("max_value_streak_threshold", 3)
	v.SetDefault("max_consecutive_failures", 10)
	v.SetDefault("gap_reboot_threshold_seconds", 1800)
	v.SetDefault("prune_removed_devices", true)
	v.SetDefault("default_port", 161)
	v.SetDefault("pushgateway_job", "pms_poller")

	v.SetEnvPrefix("POLLER")
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	if cfgFile != "" {
		v.SetConfigFile(cfgFile)
	} else {
		v.SetConfigName("config")
		v.SetConfigType("yaml")
		v.AddConfigPath(".")
		v.AddConfigPath("/etc/pms-poller")
	}

	if err := v.ReadInConfig(); err != nil {
		if _, ok := err.(viper.ConfigFileNotFoundError); !ok {
			return nil, fmt.Errorf("read config: %w", err)
		}
	}

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("unmarshal config: %w", err)
	}

	if cfg.Concurrency <= 0 {
		return nil, fmt.Errorf("concurrency must be > 0")
	}
	if cfg.SNMPTimeout <= 0 {
		return nil, fmt.Errorf("snmp_timeout must be > 0")
	}
	if cfg.DefaultPort == 0 {
		cfg.DefaultPort = 161
	}
	if cfg.UptimeBatchSize <= 0 {
		cfg.UptimeBatchSize = 500
	}

	return &cfg, nil
}
