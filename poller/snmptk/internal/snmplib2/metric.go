package snmplib2

import (
	"database/sql"
	"encoding/json"
	"log"
	"time"
)

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
