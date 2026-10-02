package adapter

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	bolt "go.etcd.io/bbolt"
)

type Config struct {
	Listen, TLSCert, TLSKey, CAFile, StateDir, ICSURL, PublicURL, XAppURL, JobID, InfoTypeID, Owner, SUPI, DNN, SD string
	SST                                                                                                            int
}
type Server struct {
	cfg     Config
	db      *bolt.DB
	client  *http.Client
	mu      sync.RWMutex
	enabled bool
}

var reports = []byte("reports")
var state = []byte("state")
var pending = []byte("pending")
var deadletter = []byte("deadletter")
var history = []byte("history")
var deliveryMeta = []byte("delivery_meta")
var deliveredBucket = []byte("delivered")

func New(c Config) (*Server, error) {
	if c.XAppURL != "" {
		u, err := url.Parse(c.XAppURL)
		if err != nil || u.Scheme != "https" || u.Host == "" {
			return nil, fmt.Errorf("XAPP_URL must be HTTPS with a hostname")
		}
	}
	if e := os.MkdirAll(c.StateDir, 0750); e != nil {
		return nil, e
	}
	db, e := bolt.Open(filepath.Join(c.StateDir, "adapter.db"), 0600, &bolt.Options{Timeout: time.Second})
	if e != nil {
		return nil, e
	}
	if e = db.Update(func(tx *bolt.Tx) error {
		for _, b := range [][]byte{reports, state, pending, deadletter, history, deliveryMeta, deliveredBucket} {
			if _, x := tx.CreateBucketIfNotExists(b); x != nil {
				return x
			}
		}
		return nil
	}); e != nil {
		db.Close()
		return nil, e
	}
	pool, e := x509.SystemCertPool()
	if e != nil {
		db.Close()
		return nil, e
	}
	if c.CAFile != "" {
		p, x := os.ReadFile(c.CAFile)
		if x != nil {
			db.Close()
			return nil, x
		}
		if !pool.AppendCertsFromPEM(p) {
			db.Close()
			return nil, fmt.Errorf("invalid CA")
		}
	}
	s := &Server{cfg: c, db: db, client: &http.Client{Timeout: 10 * time.Second, Transport: &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: pool}}}}
	s.exportDeadletter()
	s.exportDeliveryLog()
	return s, nil
}
func (s *Server) Close() error { return s.db.Close() }
func (s *Server) Handler() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("/healthz", s.health)
	m.HandleFunc("/readyz", s.ready)
	m.HandleFunc("/callbacks/a1-ei/results/", s.result)
	m.HandleFunc("/callbacks/a1-ei/status/", s.status)
	m.HandleFunc("/v1/urr", s.list)
	m.HandleFunc("/v1/urr/latest", s.latest)
	m.HandleFunc("/v1/delivery/status", s.deliveryStatus)
	return m
}
func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	io.WriteString(w, `{"status":"ok"}`)
}
func (s *Server) ready(w http.ResponseWriter, _ *http.Request) {
	s.mu.RLock()
	v := s.enabled
	s.mu.RUnlock()
	if !v {
		http.Error(w, "EI job not ENABLED", 503)
		return
	}
	s.health(w, nil)
}
func (s *Server) result(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "method", 405)
		return
	}
	if strings.TrimPrefix(r.URL.Path, "/callbacks/a1-ei/results/") != s.cfg.JobID {
		http.Error(w, "job", 404)
		return
	}
	b, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if e != nil || !json.Valid(b) {
		http.Error(w, "invalid JSON", 400)
		return
	}
	var v struct {
		SEID  json.Number `json:"seid"`
		Seq   json.Number `json:"ur_seqn"`
		Epoch string      `json:"session_epoch"`
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	if dec.Decode(&v) != nil {
		http.Error(w, "invalid URR", 400)
		return
	}
	seid, e1 := strconv.ParseUint(v.SEID.String(), 10, 64)
	seq, e2 := strconv.ParseUint(v.Seq.String(), 10, 64)
	if e1 != nil || e2 != nil || seid == 0 || seq == 0 {
		http.Error(w, "invalid SEID/UR-SEQN", 400)
		return
	}
	// session_epoch separates sessions that reuse a SEID (producer schema
	// 1.1.0); reports without it keep the original (SEID, UR-SEQN) key.
	key := fmt.Sprintf("%d:%d", seid, seq)
	if v.Epoch != "" {
		if !validEpoch(v.Epoch) {
			http.Error(w, "invalid session_epoch", 400)
			return
		}
		key = fmt.Sprintf("%d:%s:%d", seid, v.Epoch, seq)
	}
	fresh := false
	e = s.db.Update(func(tx *bolt.Tx) error {
		x := tx.Bucket(reports)
		if old := x.Get([]byte(key)); old != nil {
			if !bytes.Equal(old, b) {
				return fmt.Errorf("conflicting report %s", key)
			}
			return nil
		}
		if s.cfg.XAppURL != "" && tx.Bucket(pending).Stats().KeyN >= 1000 {
			return errQueueFull
		}
		fresh = true
		if e := x.Put([]byte(key), b); e != nil {
			return e
		}
		if s.cfg.XAppURL != "" {
			if e := tx.Bucket(pending).Put([]byte(key), b); e != nil {
				return e
			}
		}
		sequence, e := tx.Bucket(history).NextSequence()
		if e != nil {
			return e
		}
		order := make([]byte, 8)
		binary.BigEndian.PutUint64(order, sequence)
		if e = tx.Bucket(history).Put(order, []byte(key)); e != nil {
			return e
		}
		return tx.Bucket(state).Put([]byte("latest"), b)
	})
	if e != nil {
		code := 500
		if e == errQueueFull {
			code = 503
		} else if strings.HasPrefix(e.Error(), "conflicting report") {
			code = 409
		}
		http.Error(w, e.Error(), code)
		return
	}
	if fresh {
		f, _ := os.OpenFile(filepath.Join(s.cfg.StateDir, "urr.jsonl"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0640)
		if f != nil {
			f.Write(append(b, '\n'))
			f.Close()
		}
	}
	w.WriteHeader(http.StatusNoContent)
}
func (s *Server) status(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "method", 405)
		return
	}
	var v map[string]any
	if json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).Decode(&v) != nil {
		http.Error(w, "bad JSON", 400)
		return
	}
	st, _ := v["eiJobStatus"].(string)
	if st == "" {
		st, _ = v["status"].(string)
	}
	s.mu.Lock()
	s.enabled = st == "ENABLED"
	s.mu.Unlock()
	w.WriteHeader(http.StatusNoContent)
}
func (s *Server) latest(w http.ResponseWriter, _ *http.Request) {
	var b []byte
	_ = s.db.View(func(tx *bolt.Tx) error {
		x := tx.Bucket(state).Get([]byte("latest"))
		if x != nil {
			b = append([]byte(nil), x...)
		}
		return nil
	})
	if b == nil {
		http.Error(w, "no reports", 404)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.Write(b)
}
func (s *Server) list(w http.ResponseWriter, r *http.Request) {
	limit := 100
	var out []json.RawMessage
	_ = s.db.View(func(tx *bolt.Tx) error {
		c := tx.Bucket(history).Cursor()
		for k, v := c.Last(); k != nil && len(out) < limit; k, v = c.Prev() {
			if report := tx.Bucket(reports).Get(v); report != nil {
				out = append(out, append([]byte(nil), report...))
			}
		}
		return nil
	})
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(out)
}
func (s *Server) Reconcile(ctx context.Context) error {
	u := strings.TrimRight(s.cfg.ICSURL, "/") + "/A1-EI/v1/eijobs/" + s.cfg.JobID
	body := map[string]any{"eiTypeId": s.cfg.InfoTypeID, "jobOwner": s.cfg.Owner, "jobResultUri": s.cfg.PublicURL + "/callbacks/a1-ei/results/" + s.cfg.JobID, "jobDefinition": map[string]any{"delivery_uri": s.cfg.PublicURL + "/callbacks/a1-ei/results/" + s.cfg.JobID, "supi": s.cfg.SUPI, "dnn": s.cfg.DNN, "sst": s.cfg.SST, "sd": s.cfg.SD}}
	b, _ := json.Marshal(body)
	req, _ := http.NewRequestWithContext(ctx, http.MethodPut, u, bytes.NewReader(b))
	req.Header.Set("Content-Type", "application/json")
	resp, e := s.client.Do(req)
	if e != nil {
		return e
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("create EI job: %s", resp.Status)
	}
	req, _ = http.NewRequestWithContext(ctx, http.MethodGet, u+"/status", nil)
	resp, e = s.client.Do(req)
	if e != nil {
		return e
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("EI job status: %s", resp.Status)
	}
	var statusBody map[string]any
	if json.NewDecoder(resp.Body).Decode(&statusBody) != nil {
		return fmt.Errorf("invalid EI status")
	}
	st, _ := statusBody["eiJobStatus"].(string)
	s.mu.Lock()
	s.enabled = st == "ENABLED"
	s.mu.Unlock()
	if st != "ENABLED" {
		return fmt.Errorf("EI job status %q", st)
	}
	return nil
}
func (s *Server) ReconcileLoop(ctx context.Context) {
	for {
		if err := s.Reconcile(ctx); err != nil {
			log.Printf("EI job reconcile: %v", err)
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(30 * time.Second):
		}
	}
}

func validEpoch(e string) bool {
	if len(e) > 32 {
		return false
	}
	for _, c := range e {
		if !(c >= '0' && c <= '9' || c == 'T' || c == 'Z') {
			return false
		}
	}
	return true
}
