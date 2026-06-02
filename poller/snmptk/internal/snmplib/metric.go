package snmplib

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/push"
)

const (
	jobName string = "pagent"
)

type DiscoveryMetric struct {
	// Grouping: agent
	// PushGatewayUrl string
	// Grouping       map[string]string
	RespTime      prometheus.Histogram // Response Time
	TargetCnt     prometheus.Gauge     // Number of ipaddr target
	TargetSuccess prometheus.Gauge     // Number of discovered device regardless if ip addr match
	DeviceErr     prometheus.Gauge     // Number of device with incomplete info
	IntfCnt       prometheus.Gauge     // Number of discovered interface
	IntfErr       prometheus.Gauge     // Number of interface with incomplete info
	IfTableErr    prometheus.Gauge     // Number of discovered device but failed during get ifTable
	DbErr         prometheus.Gauge     // Number of Database operation error
}

type IfTableMetric struct {
	// Grouping: agent, type, network
	// PushGatewayUrl string
	// Grouping       map[string]string
	RespTime      prometheus.Histogram // Response Time
	DeviceSuccess prometheus.Gauge     // total device success
	DeviceError   prometheus.Gauge     // total deice error
	IntfCnt       prometheus.Gauge     // total intf return from get ifXTable
	IntfErr       prometheus.Gauge     // total intf with invalid data
	IntfNew       prometheus.Gauge     // total intf with new data (no previous saved value)
	IntfExpired   prometheus.Gauge     // total intf with expired time delta
	IntfReset     prometheus.Gauge     // total intf with ifCounterDiscontinuityTime changed from last saved
	DeltaNormal   float64              // delta value with status normal
	DeltaZero     float64              // delta value with status zero
	DeltaReset    float64              // delta value with status reset
	DeltaOverflow float64              // delta value with status overflow
	DeltaOverrate float64              // delta value with status overrate
	DeltaErr      float64              // delta value with status error
}

type IfTableMetricGroup struct {
	Agent    string
	PollType string
	Network  string
}

type PollStatus struct {
	Start    JsonTime `json:"start,omitempty"`    // start time
	PollType string   `json:"polltype,omitempty"` // traffic5m, traffic15m
	Network  string   `json:"network,omitempty"`  // device.network
	Agent    string   `json:"agent,omitempty"`    // pagent hostname
	Success  int      `json:"success,omitempty"`  // number of success device
	Error    int      `json:"error,omitempty"`    // number of error device
}

type PollStatusErr struct {
	Tstamp   JsonTime `json:"tstamp,omitempty"`
	Ip       string   `json:"ip,omitempty"`
	Agent    string   `json:"agent,omitempty"`    // pagent hostname
	PollType string   `json:"polltype,omitempty"` // traffic5m, traffic15m
	Network  string   `json:"network,omitempty"`  // device.network
	Errmsg   string   `json:"errmsg,omitempty"`
}

func NewDiscoveryMetric() *DiscoveryMetric {
	metric := DiscoveryMetric{
		RespTime:      newHistogram("pagent_disc_resptime_seconds", "Response Time", 2, 2, 10),
		TargetCnt:     newGauge("pagent_disc_target_cnt", "Number of ipaddr target"),
		TargetSuccess: newGauge("pagent_disc_target_success", "Number of discovered device"),
		DeviceErr:     newGauge("pagent_disc_device_err", "Number of device with incomplete info"),
		IntfCnt:       newGauge("pagent_disc_intf_cnt", "Number of discovered interface"),
		IntfErr:       newGauge("pagent_disc_intf_err", "Number of interface with incomplete info"),
		IfTableErr:    newGauge("pagent_disc_iftable_err", "Number of discovered device but failed during get ifTable"),
		DbErr:         newGauge("pagent_disc_db_err", "Number of Database operation error"),
	}
	return &metric
}

func NewSnmpIfTableMetric() *IfTableMetric {
	metric := IfTableMetric{
		RespTime:      newHistogram("pagent_iftable_resptime_seconds", "Response Time", 2, 2, 10),
		DeviceSuccess: newGauge("pagent_iftable_device_success", "Number of Device Success"),
		DeviceError:   newGauge("pagent_iftable_device_err", "Number of Device Error"),
		IntfCnt:       newGauge("pagent_iftable_intf_cnt", "Total Interface"),
		IntfErr:       newGauge("pagent_iftable_intf_err", "Total Interface with invalid data"),
		IntfNew:       newGauge("pagent_iftable_intf_new", "Total Interface with new data (no previous saved value)"),
		IntfExpired:   newGauge("pagent_iftable_intf_expired", "Total Interface with expired time"),
		IntfReset:     newGauge("pagent_iftable_intf_reset", "Total Interface with reset conuter"),
		// Delta: newGuageVec("pagent_iftable_delta", "Total delta with status normal", []string{"normal", "zero", "reset", "overflow", "overrate", "error"}),
	}
	return &metric
}

func PushDiscoveryMetric(setting *AppSetting, metric *DiscoveryMetric) {
	if setting.MetricUrl != "" {
		agent, _ := os.Hostname()
		pusher := push.New(setting.MetricUrl, jobName)
		pusher.Client(&http.Client{Timeout: time.Duration(5) * time.Second})

		pusher.Grouping("agent", agent)
		pusher.Collector(metric.RespTime)
		pusher.Collector(metric.TargetCnt)
		pusher.Collector(metric.TargetSuccess)
		pusher.Collector(metric.DeviceErr)
		pusher.Collector(metric.IntfCnt)
		pusher.Collector(metric.IntfErr)
		pusher.Collector(metric.IfTableErr)
		pusher.Collector(metric.DbErr)

		err := pusher.Push()
		if err != nil {
			log.Printf("Error! Could not push metric: %v", err)
		} else {
			log.Printf("PushDiscoveryMetric: %v", setting.MetricUrl)
			s, _ := json.MarshalIndent(metric, "", " ")
			log.Printf("metric = %v", string(s))
		}
	}
}

func PushSnmpIfTableMetric(setting *AppSetting, metrics map[IfTableMetricGroup]*IfTableMetric) {
	if setting.MetricUrl != "" {
		for grp, metric := range metrics {
			pusher := push.New(setting.MetricUrl, jobName)
			pusher.Client(&http.Client{Timeout: time.Duration(5) * time.Second})

			pusher.Grouping("agent", grp.Agent)
			pusher.Grouping("polltype", grp.PollType)
			pusher.Grouping("network", grp.Network)

			pusher.Collector(metric.RespTime)
			pusher.Collector(metric.DeviceSuccess)
			pusher.Collector(metric.DeviceError)
			pusher.Collector(metric.IntfCnt)
			pusher.Collector(metric.IntfNew)
			pusher.Collector(metric.IntfExpired)

			delta := newGuageVec("pagent_iftable_delta", "Delta breakdown by status", []string{"status"})
			delta.With(prometheus.Labels{"status": "normal"}).Set(metric.DeltaNormal)
			delta.With(prometheus.Labels{"status": "zero"}).Set(metric.DeltaZero)
			delta.With(prometheus.Labels{"status": "reset"}).Set(metric.DeltaReset)
			delta.With(prometheus.Labels{"status": "overflow"}).Set(metric.DeltaOverflow)
			delta.With(prometheus.Labels{"status": "overrate"}).Set(metric.DeltaOverrate)
			delta.With(prometheus.Labels{"status": "error"}).Set(metric.DeltaErr)
			pusher.Collector(delta)

			err := pusher.Push()
			if err != nil {
				log.Printf("Error! Could not push metric: %v", err)
			} else {
				log.Printf("PushSnmpPollIfTableMetric: %v", setting.MetricUrl)
				// s0, _ := json.MarshalIndent(grp, "", " ")
				// s1, _ := json.MarshalIndent(metric, "", " ")
				// log.Printf("group  = %v", string(s0))
				// log.Printf("metric = %v", string(s1))
			}
		}
	}
}

func newGauge(name string, help string) prometheus.Gauge {
	m := prometheus.NewGauge(prometheus.GaugeOpts{
		Name: name,
		Help: help,
	})
	return m
}

func newGuageVec(name string, help string, labels []string) prometheus.GaugeVec {
	m := prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: name,
		Help: help,
	}, labels)
	return *m
}

func newHistogram(name string, help string, start float64, width float64, count int) prometheus.Histogram {
	m := prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:    name,
		Help:    help,
		Buckets: prometheus.LinearBuckets(start, width, count),
	})
	return m
}

func savePollStatus(dbConnection string, pollStatusMap map[string]*PollStatus, pollStatusErr []PollStatusErr, cnt_ok int, cnt_err int) {
	// Connect to database
	// connStr := "postgresql://pmsonline:pmsonline@hd2.hdp:5432/pmsonline?sslmode=disable&connect_timeout=10"
	t := time.Now()
	log.Printf("savePollStatus PollStatus: %d entries, PollStatusErr: %d entries", len(pollStatusMap), len(pollStatusErr))

	db, err := sql.Open("postgres", dbConnection)
	if err != nil {
		log.Printf("Error! %v", err)
	}
	defer db.Close()

	// Begin Tx
	tx, err := db.Begin()
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}

	// PollStatus
	completed := time.Now()
	poll_ids := make(map[string]int)
	for _, entry := range pollStatusMap {
		var poll_id int
		var pct_success float64
		var total = entry.Success + entry.Error
		if total > 0 {
			pct_success = float64((float64(entry.Success) / float64(total)) * float64(100))
		}

		s, _ := json.MarshalIndent(entry, "", " ")
		log.Printf("PollStatus = %v", string(s))

		err = tx.QueryRow(`
			insert into pollstatus(id, polltype, start, completed, network, agent, success, error, pct_success)
				values(nextval('pollstatus_seq'), $1, $2, $3, $4, $5, $6, $7, $8)
				returning id`,
			entry.PollType, time.Time(entry.Start), completed, entry.Network, entry.Agent, entry.Success, entry.Error, pct_success).Scan(&poll_id)
		if err != nil {
			log.Printf("Error! %v", err)
			return
		}
		poll_ids[entry.Network] = poll_id
	}

	// PollStatusErr
	stmt, err := tx.Prepare(`insert into pollstatus_err(id, pollstatus_id, polltype, tstamp, ip, network, agent, errmsg)
													 values(nextval('pollstatus_seq'), $1, $2, $3, $4, $5, $6, $7)`)
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}

	for _, entry := range pollStatusErr {
		poll_id, ok := poll_ids[entry.Network]
		if ok {
			log.Printf("PollStatusErr|%v|%v|%v|%v|%v|%v|%v", entry.PollType, poll_id, entry.Tstamp.Format("20060102T1504"), entry.Ip, entry.Network, entry.Agent, entry.Errmsg)
			_, err := stmt.Exec(poll_id, entry.PollType, time.Time(entry.Tstamp), entry.Ip, entry.Network, entry.Agent, entry.Errmsg)
			if err != nil {
				log.Printf("Error! %v", err)
				return
			}
		}
	}

	// Commit
	err = tx.Commit()
	if err != nil {
		log.Printf("Error! %v", err)
		return
	}
	log.Printf("savePollStatusErr %d entries in %s", len(pollStatusErr), time.Since(t))
}
