package adapter

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

	bolt "go.etcd.io/bbolt"
)

var errQueueFull = errors.New("xApp delivery queue full")

type deliveryRecord struct {
	Attempts    int    `json:"attempts"`
	LastAttempt string `json:"last_attempt"`
	LastStatus  string `json:"last_status"`
}

func (s *Server) recordAttempt(key []byte, status string) {
	var rec deliveryRecord
	_ = s.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(deliveryMeta)
		if old := bucket.Get(key); old != nil {
			_ = json.Unmarshal(old, &rec)
		}
		rec.Attempts++
		rec.LastAttempt = time.Now().UTC().Format(time.RFC3339Nano)
		rec.LastStatus = status
		b, _ := json.Marshal(rec)
		return bucket.Put(key, b)
	})
	s.appendDeliveryLog(key, rec)
}

// appendDeliveryLog adds one attempt to delivery-status.jsonl; the last line
// of an event is its current state. Rewriting the whole log per attempt
// (exportDeliveryLog, now only at startup) cost O(delivered) per report and
// fell behind two UEs at 1 s URR after a day (found in R2).
func (s *Server) appendDeliveryLog(key []byte, rec deliveryRecord) {
	file, err := os.OpenFile(filepath.Join(s.cfg.StateDir, "delivery-status.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	entry, _ := json.Marshal(map[string]any{"event_id": s.eventID(key), "attempts": rec.Attempts, "last_attempt": rec.LastAttempt, "last_status": rec.LastStatus})
	_, _ = file.Write(append(entry, '\n'))
	_ = file.Close()
}

func (s *Server) exportDeliveryLog() {
	path := filepath.Join(s.cfg.StateDir, "delivery-status.jsonl")
	file, err := os.Create(path + ".tmp")
	if err != nil {
		return
	}
	_ = s.db.View(func(tx *bolt.Tx) error {
		c := tx.Bucket(deliveryMeta).Cursor()
		for k, v := c.First(); k != nil; k, v = c.Next() {
			var rec deliveryRecord
			if json.Unmarshal(v, &rec) != nil {
				continue
			}
			entry, _ := json.Marshal(map[string]any{"event_id": s.eventID(k), "attempts": rec.Attempts, "last_attempt": rec.LastAttempt, "last_status": rec.LastStatus})
			_, _ = file.Write(append(entry, '\n'))
		}
		return nil
	})
	syncErr := file.Sync()
	closeErr := file.Close()
	if syncErr == nil && closeErr == nil {
		_ = os.Rename(path+".tmp", path)
	} else {
		_ = os.Remove(path + ".tmp")
	}
}

func (s *Server) exportDeadletter() {
	path := filepath.Join(s.cfg.StateDir, "delivery-dead-letter.jsonl")
	file, err := os.Create(path + ".tmp")
	if err != nil {
		return
	}
	_ = s.db.View(func(tx *bolt.Tx) error {
		c := tx.Bucket(deadletter).Cursor()
		for k, v := c.First(); k != nil; k, v = c.Next() {
			entry, _ := json.Marshal(map[string]any{"event_id": s.eventID(k), "report": json.RawMessage(v)})
			_, _ = file.Write(append(entry, '\n'))
		}
		return nil
	})
	syncErr := file.Sync()
	closeErr := file.Close()
	if syncErr == nil && closeErr == nil {
		_ = os.Rename(path+".tmp", path)
	} else {
		_ = os.Remove(path + ".tmp")
	}
}

type envelope struct {
	EventID string          `json:"event_id"`
	JobID   string          `json:"job_id"`
	Report  json.RawMessage `json:"report"`
}

func (s *Server) deliveryStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method", 405)
		return
	}
	var queued, delivered, dead int
	perKind := map[string]map[string]int{}
	count := func(b *bolt.Bucket, what string) {
		_ = b.ForEach(func(k, _ []byte) error {
			st, _ := s.splitKey(k)
			if perKind[st.Kind] == nil {
				perKind[st.Kind] = map[string]int{}
			}
			perKind[st.Kind][what]++
			return nil
		})
	}
	_ = s.db.View(func(tx *bolt.Tx) error {
		queued = tx.Bucket(pending).Stats().KeyN
		dead = tx.Bucket(deadletter).Stats().KeyN
		delivered = tx.Bucket(deliveredBucket).Stats().KeyN
		if len(s.cfg.Extra) > 0 {
			count(tx.Bucket(pending), "queued")
			count(tx.Bucket(deadletter), "dead_letter")
			count(tx.Bucket(deliveredBucket), "delivered")
		}
		return nil
	})
	out := map[string]any{"queued": queued, "delivered": delivered, "dead_letter": dead}
	if len(s.cfg.Extra) > 0 {
		s.mu.RLock()
		jobs := map[string]string{}
		for k, v := range s.jobStatus {
			jobs[k] = v
		}
		s.mu.RUnlock()
		out["streams"] = perKind
		out["jobs"] = jobs
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

// DeliveryLoop is independent of the A1-EI callback: only an xApp ACK removes
// a pending report. A lost ACK is safe because the xApp deduplicates event_id.
func (s *Server) DeliveryLoop(ctx context.Context) {
	if s.cfg.XAppURL == "" {
		return
	}
	client := *s.client
	client.Timeout = 5 * time.Second
	delay := time.Second
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		var key, report []byte
		_ = s.db.View(func(tx *bolt.Tx) error {
			k, v := tx.Bucket(pending).Cursor().First()
			key = append([]byte(nil), k...)
			report = append([]byte(nil), v...)
			return nil
		})
		if len(key) == 0 {
			select {
			case <-ctx.Done():
				return
			case <-time.After(time.Second):
			}
			continue
		}
		st, _ := s.splitKey(key)
		body, _ := json.Marshal(envelope{EventID: s.eventID(key), JobID: st.JobID, Report: report})
		recorded := false
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.XAppURL+"/v1/"+st.Kind+"/events", bytes.NewReader(body))
		if err == nil {
			req.Header.Set("Content-Type", "application/json")
			var resp *http.Response
			resp, err = client.Do(req)
			if err == nil {
				resp.Body.Close()
				s.recordAttempt(key, fmt.Sprintf("HTTP %d", resp.StatusCode))
				recorded = true
				switch resp.StatusCode {
				case 200, 201:
					err = s.db.Update(func(tx *bolt.Tx) error {
						if e := tx.Bucket(deliveredBucket).Put(key, []byte(time.Now().UTC().Format(time.RFC3339Nano))); e != nil {
							return e
						}
						return tx.Bucket(pending).Delete(key)
					})
					if err == nil {
						delay = time.Second
						continue
					}
				case 400, 409:
					err = s.db.Update(func(tx *bolt.Tx) error {
						if e := tx.Bucket(deadletter).Put(key, report); e != nil {
							return e
						}
						return tx.Bucket(pending).Delete(key)
					})
					if err == nil {
						s.exportDeadletter()
						delay = time.Second
						continue
					}
				default:
					err = fmt.Errorf("xApp HTTP %d", resp.StatusCode)
				}
			}
		}
		if err != nil { // Keep report in BoltDB on network or server failure.
			if !recorded {
				s.recordAttempt(key, err.Error())
			}
			select {
			case <-ctx.Done():
				return
			case <-time.After(delay):
			}
			if delay < 30*time.Second {
				delay *= 2
				if delay > 30*time.Second {
					delay = 30 * time.Second
				}
			}
		}
	}
}
