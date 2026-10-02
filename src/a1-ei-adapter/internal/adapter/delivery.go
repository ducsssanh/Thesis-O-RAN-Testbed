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
	_ = s.db.Update(func(tx *bolt.Tx) error {
		bucket := tx.Bucket(deliveryMeta)
		var rec deliveryRecord
		if old := bucket.Get(key); old != nil {
			_ = json.Unmarshal(old, &rec)
		}
		rec.Attempts++
		rec.LastAttempt = time.Now().UTC().Format(time.RFC3339Nano)
		rec.LastStatus = status
		b, _ := json.Marshal(rec)
		return bucket.Put(key, b)
	})
	s.exportDeliveryLog()
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
			entry, _ := json.Marshal(map[string]any{"event_id": s.cfg.JobID + ":" + string(k), "attempts": rec.Attempts, "last_attempt": rec.LastAttempt, "last_status": rec.LastStatus})
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
			entry, _ := json.Marshal(map[string]any{"event_id": s.cfg.JobID + ":" + string(k), "report": json.RawMessage(v)})
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
	_ = s.db.View(func(tx *bolt.Tx) error {
		queued = tx.Bucket(pending).Stats().KeyN
		dead = tx.Bucket(deadletter).Stats().KeyN
		delivered = tx.Bucket(deliveredBucket).Stats().KeyN
		return nil
	})
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]int{"queued": queued, "delivered": delivered, "dead_letter": dead})
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
		body, _ := json.Marshal(envelope{EventID: s.cfg.JobID + ":" + string(key), JobID: s.cfg.JobID, Report: report})
		recorded := false
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, s.cfg.XAppURL+"/v1/urr/events", bytes.NewReader(body))
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
