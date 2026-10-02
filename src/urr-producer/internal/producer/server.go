package producer

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	bolt "go.etcd.io/bbolt"
)

var jobsBucket = []byte("jobs")
var seenBucket = []byte("seen")
var stateBucket = []byte("state")
var pendingBucket = []byte("pending")
var epochsBucket = []byte("epochs")

type Server struct {
	cfg        Config
	db         *bolt.DB
	client     *http.Client
	kubeClient *http.Client
	mu         sync.RWMutex
	ready      bool
}
type pendingDelivery struct {
	Report   Normalized `json:"report"`
	Attempts int        `json:"attempts"`
	NextAt   time.Time  `json:"next_at"`
}

func New(c Config) (*Server, error) {
	if err := os.MkdirAll(c.StateDir, 0750); err != nil {
		return nil, err
	}
	db, err := bolt.Open(filepath.Join(c.StateDir, "producer.db"), 0600, &bolt.Options{Timeout: time.Second})
	if err != nil {
		return nil, err
	}
	err = db.Update(func(tx *bolt.Tx) error {
		for _, b := range [][]byte{jobsBucket, seenBucket, stateBucket, pendingBucket, epochsBucket} {
			if _, e := tx.CreateBucketIfNotExists(b); e != nil {
				return e
			}
		}
		return nil
	})
	if err != nil {
		db.Close()
		return nil, err
	}
	pool, err := x509.SystemCertPool()
	if err != nil {
		db.Close()
		return nil, err
	}
	if c.CAFile != "" {
		pem, er := os.ReadFile(c.CAFile)
		if er != nil {
			db.Close()
			return nil, er
		}
		if !pool.AppendCertsFromPEM(pem) {
			db.Close()
			return nil, fmt.Errorf("invalid CA file")
		}
	}
	tr := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: pool}}
	kubePool := x509.NewCertPool()
	kubeCA, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
	if err == nil {
		kubePool.AppendCertsFromPEM(kubeCA)
	}
	kubeTransport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: kubePool}}
	return &Server{cfg: c, db: db, client: &http.Client{Timeout: 10 * time.Second, Transport: tr}, kubeClient: &http.Client{Timeout: 5 * time.Second, Transport: kubeTransport}}, nil
}
func (s *Server) Close() error { return s.db.Close() }
func (s *Server) Handler() http.Handler {
	m := http.NewServeMux()
	m.HandleFunc("/healthz", s.health)
	m.HandleFunc("/readyz", s.readiness)
	m.HandleFunc("/callbacks/smf", s.smf)
	m.HandleFunc("/callbacks/ics/supervision", s.health)
	m.HandleFunc("/callbacks/ics/jobs", s.jobs)
	m.HandleFunc("/callbacks/ics/jobs/", s.deleteJob)
	return m
}
func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	io.WriteString(w, `{"status":"ok"}`)
}
func (s *Server) readiness(w http.ResponseWriter, _ *http.Request) {
	s.mu.RLock()
	r := s.ready
	s.mu.RUnlock()
	if !r {
		http.Error(w, "not reconciled", 503)
		return
	}
	s.health(w, nil)
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	defer r.Body.Close()
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	d.DisallowUnknownFields()
	if err := d.Decode(v); err != nil {
		http.Error(w, err.Error(), 400)
		return false
	}
	return true
}
func (s *Server) jobs(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "method", 405)
		return
	}
	var j Job
	if !decode(w, r, &j) {
		return
	}
	if j.ID == "" || j.InformationType != s.cfg.InfoTypeID {
		http.Error(w, "invalid job", 400)
		return
	}
	var data map[string]any
	if err := json.Unmarshal(j.Data, &data); err != nil {
		http.Error(w, "invalid info_job_data", 400)
		return
	}
	if j.TargetURI == "" {
		if x, ok := data["delivery_uri"].(string); ok {
			j.TargetURI = x
		}
	}
	if !strings.HasPrefix(j.TargetURI, "https://") {
		http.Error(w, "HTTPS target_uri required", 400)
		return
	}
	b, _ := json.Marshal(j)
	if err := s.db.Update(func(tx *bolt.Tx) error { return tx.Bucket(jobsBucket).Put([]byte(j.ID), b) }); err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	w.WriteHeader(200)
}
func (s *Server) deleteJob(w http.ResponseWriter, r *http.Request) {
	if r.Method != "DELETE" {
		http.Error(w, "method", 405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/callbacks/ics/jobs/")
	if id == "" {
		http.Error(w, "missing id", 400)
		return
	}
	if err := s.db.Update(func(tx *bolt.Tx) error {
		if err := tx.Bucket(jobsBucket).Delete([]byte(id)); err != nil {
			return err
		}
		prefix := []byte(id + ":")
		cursor := tx.Bucket(pendingBucket).Cursor()
		for key, _ := cursor.Seek(prefix); key != nil && bytes.HasPrefix(key, prefix); key, _ = cursor.Next() {
			if err := cursor.Delete(); err != nil {
				return err
			}
		}
		return nil
	}); err != nil {
		http.Error(w, err.Error(), 500)
		return
	}
	w.WriteHeader(200)
}
func appendJSON(path string, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return e
	}
	f, e := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0640)
	if e != nil {
		return e
	}
	defer f.Close()
	_, e = f.Write(append(b, '\n'))
	return e
}
func (s *Server) smf(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		http.Error(w, "method", 405)
		return
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 2<<20))
	if err != nil {
		http.Error(w, err.Error(), 400)
		return
	}
	if !json.Valid(raw) {
		http.Error(w, "invalid JSON", 400)
		return
	}
	if err := appendJSON(filepath.Join(s.cfg.StateDir, "smf-raw.jsonl"), json.RawMessage(raw)); err != nil {
		http.Error(w, "audit write failed", 500)
		return
	}
	var n Notification
	d := json.NewDecoder(bytes.NewReader(raw))
	if err = d.Decode(&n); err != nil || len(n.Events) == 0 {
		_ = appendJSON(filepath.Join(s.cfg.StateDir, "errors.jsonl"), map[string]any{"at": time.Now().UTC(), "error": fmt.Sprint(err), "raw": string(raw)})
		http.Error(w, "invalid notification", 400)
		return
	}
	accepted := 0
	valid := 0
	for _, e := range n.Events {
		v, er := Normalize(e, s.cfg, time.Now())
		if er != nil {
			_ = appendJSON(filepath.Join(s.cfg.StateDir, "errors.jsonl"), map[string]any{"at": time.Now().UTC(), "error": er.Error()})
			continue
		}
		valid++
		start := sessionStart(v, time.Now())
		fp := fingerprint(v)
		key := ""
		fresh := false
		er = s.db.Update(func(tx *bolt.Tx) error {
			b := tx.Bucket(seenBucket)
			epochs := tx.Bucket(epochsBucket)
			sessionKey := []byte(fmt.Sprintf("%s|%d", v.SUPI, v.SEID))
			var prev *epochState
			stored := ""
			if raw := epochs.Get(sessionKey); raw != nil {
				prev = &epochState{}
				if err := json.Unmarshal(raw, prev); err != nil {
					return err
				}
				stored = string(b.Get([]byte(fmt.Sprintf("%d:%s:%d", v.SEID, prev.Epoch, v.URSequence))))
			}
			epoch, duplicate, next := assignEpoch(prev, start, v.URSequence, fp, stored)
			v.SessionEpoch = epoch
			key = fmt.Sprintf("%d:%s:%d", v.SEID, epoch, v.URSequence)
			state, err := json.Marshal(next)
			if err != nil {
				return err
			}
			if err := epochs.Put(sessionKey, state); err != nil {
				return err
			}
			if duplicate {
				return nil
			}
			if tx.Bucket(pendingBucket).Stats().KeyN >= 1000 {
				return fmt.Errorf("delivery queue full")
			}
			payload, err := json.Marshal(pendingDelivery{Report: v})
			if err != nil {
				return err
			}
			if err := tx.Bucket(jobsBucket).ForEach(func(jobID, jobData []byte) error {
				var job Job
				if err := json.Unmarshal(jobData, &job); err != nil {
					return err
				}
				if !matches(job, v) {
					return nil
				}
				return tx.Bucket(pendingBucket).Put([]byte(string(jobID)+":"+key), payload)
			}); err != nil {
				return err
			}
			fresh = true
			return b.Put([]byte(key), []byte(fp))
		})
		if er != nil {
			http.Error(w, er.Error(), 500)
			return
		}
		if !fresh {
			continue
		}
		accepted++
		_ = appendJSON(filepath.Join(s.cfg.StateDir, "normalized.jsonl"), v)
		s.appendCSV(v)
	}
	if valid == 0 {
		http.Error(w, "no valid QOS_MON Usage Report", 400)
		return
	}
	if accepted == 0 {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
func (s *Server) appendCSV(v Normalized) {
	p := filepath.Join(s.cfg.StateDir, "normalized.csv")
	_, stat := os.Stat(p)
	f, e := os.OpenFile(p, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0640)
	if e != nil {
		return
	}
	defer f.Close()
	c := csv.NewWriter(f)
	defer c.Flush()
	if os.IsNotExist(stat) {
		_ = c.Write([]string{"run_id", "observed_at", "supi", "seid", "session_epoch", "urr_id", "ur_seqn", "trigger", "ul_bytes", "dl_bytes", "total_bytes", "ul_packets", "dl_packets", "total_packets", "duration_seconds", "dnn", "sst", "sd"})
	}
	urr := ""
	if v.URRID != nil {
		urr = strconv.FormatUint(*v.URRID, 10)
	}
	_ = c.Write([]string{v.RunID, v.ObservedAt, v.SUPI, strconv.FormatUint(v.SEID, 10), v.SessionEpoch, urr, strconv.FormatUint(v.URSequence, 10), strings.Join(v.Triggers, "|"), strconv.FormatUint(v.ULBytes, 10), strconv.FormatUint(v.DLBytes, 10), strconv.FormatUint(v.TotalBytes, 10), strconv.FormatUint(v.ULPackets, 10), strconv.FormatUint(v.DLPackets, 10), strconv.FormatUint(v.TotalPackets, 10), strconv.FormatUint(v.DurationSeconds, 10), v.DNN, strconv.Itoa(v.SNSSAI.SST), v.SNSSAI.SD})
}
func matches(j Job, v Normalized) bool {
	var d map[string]any
	if json.Unmarshal(j.Data, &d) != nil {
		return false
	}
	for _, x := range []struct{ key, value string }{{"supi", v.SUPI}, {"dnn", v.DNN}, {"sd", v.SNSSAI.SD}} {
		if wanted, ok := d[x.key].(string); ok && wanted != "" && wanted != x.value {
			return false
		}
	}
	if wanted, ok := d["sst"].(float64); ok && int(wanted) != v.SNSSAI.SST {
		return false
	}
	return true
}
func (s *Server) DeliverPending(ctx context.Context) {
	for {
		s.deliverBatch(ctx)
		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}
}
func (s *Server) deliverBatch(ctx context.Context) {
	type item struct {
		key     string
		pending pendingDelivery
		target  string
	}
	items := []item{}
	_ = s.db.View(func(tx *bolt.Tx) error {
		c := tx.Bucket(pendingBucket).Cursor()
		for k, b := c.First(); k != nil && len(items) < 50; k, b = c.Next() {
			jobID, _, _ := strings.Cut(string(k), ":")
			raw := tx.Bucket(jobsBucket).Get([]byte(jobID))
			if raw == nil {
				continue
			}
			var j Job
			var pending pendingDelivery
			if json.Unmarshal(raw, &j) == nil && json.Unmarshal(b, &pending) == nil && !time.Now().Before(pending.NextAt) {
				items = append(items, item{string(k), pending, j.TargetURI})
			}
		}
		return nil
	})
	for _, it := range items {
		body, _ := json.Marshal(it.pending.Report)
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, it.target, bytes.NewReader(body))
		if err != nil {
			continue
		}
		req.Header.Set("Content-Type", "application/json")
		resp, err := s.client.Do(req)
		if err == nil {
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
		}
		if err == nil && resp.StatusCode >= 200 && resp.StatusCode < 300 {
			_ = s.db.Update(func(tx *bolt.Tx) error { return tx.Bucket(pendingBucket).Delete([]byte(it.key)) })
			continue
		}
		message := "request failed"
		if err != nil {
			message = err.Error()
		} else {
			message = resp.Status
		}
		it.pending.Attempts++
		if it.pending.Attempts >= 6 {
			_ = appendJSON(filepath.Join(s.cfg.StateDir, "dead-letter.jsonl"), map[string]any{"at": time.Now().UTC(), "key": it.key, "error": message, "report": it.pending.Report})
			_ = s.db.Update(func(tx *bolt.Tx) error { return tx.Bucket(pendingBucket).Delete([]byte(it.key)) })
		} else {
			it.pending.NextAt = time.Now().Add(time.Second * time.Duration(1<<it.pending.Attempts))
			data, _ := json.Marshal(it.pending)
			_ = s.db.Update(func(tx *bolt.Tx) error { return tx.Bucket(pendingBucket).Put([]byte(it.key), data) })
		}
		_ = appendJSON(filepath.Join(s.cfg.StateDir, "delivery-errors.jsonl"), map[string]any{"at": time.Now().UTC(), "key": it.key, "error": message})
	}
}
func putJSON(ctx context.Context, c *http.Client, method, url string, v any) (*http.Response, error) {
	b, _ := json.Marshal(v)
	req, e := http.NewRequestWithContext(ctx, method, url, bytes.NewReader(b))
	if e != nil {
		return nil, e
	}
	req.Header.Set("Content-Type", "application/json")
	return c.Do(req)
}
func (s *Server) Reconcile(ctx context.Context) error {
	typeBody := map[string]any{"info_type_information": map[string]any{"schema_version": "1.0.0", "delivery": "HTTPS JSON", "description": "OAI PFCP usage report exposed as A1-EI"}, "info_job_data_schema": map[string]any{"type": "object", "required": []string{"delivery_uri"}, "properties": map[string]any{"delivery_uri": map[string]string{"type": "string", "format": "uri"}, "supi": map[string]string{"type": "string"}, "dnn": map[string]string{"type": "string"}, "sst": map[string]string{"type": "integer"}, "sd": map[string]string{"type": "string"}}}}
	for _, x := range []struct {
		url  string
		body any
	}{{strings.TrimRight(s.cfg.ICSURL, "/") + "/data-producer/v1/info-types/" + s.cfg.InfoTypeID, typeBody}, {strings.TrimRight(s.cfg.ICSURL, "/") + "/data-producer/v1/info-producers/" + s.cfg.ProducerID, map[string]any{"info_producer_supervision_callback_url": s.cfg.PublicURL + "/callbacks/ics/supervision", "supported_info_types": []string{s.cfg.InfoTypeID}, "info_job_callback_url": s.cfg.PublicURL + "/callbacks/ics/jobs"}}} {
		resp, err := putJSON(ctx, s.client, http.MethodPut, x.url, x.body)
		if err != nil {
			return err
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("ICS %s: %s", x.url, resp.Status)
		}
	}
	callback := s.cfg.PublicURL + "/callbacks/smf"
	podUID, err := s.smfPodUID(ctx)
	if err != nil {
		return err
	}
	var subscribedUID string
	_ = s.db.View(func(tx *bolt.Tx) error {
		subscribedUID = string(tx.Bucket(stateBucket).Get([]byte("smf-pod-uid")))
		return nil
	})
	if podUID == subscribedUID {
		s.mu.Lock()
		s.ready = true
		s.mu.Unlock()
		return nil
	}
	body := map[string]any{"notifId": s.cfg.ProducerID, "notifUri": callback, "eventSubs": []any{map[string]any{"event": "QOS_MON"}}}
	resp, err := putJSON(ctx, s.client, http.MethodPost, strings.TrimRight(s.cfg.SMFURL, "/")+"/nsmf_event-exposure/v1/subscriptions", body)
	if err != nil {
		return err
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusConflict {
		return fmt.Errorf("SMF subscription: %s", resp.Status)
	}
	if err := s.db.Update(func(tx *bolt.Tx) error { return tx.Bucket(stateBucket).Put([]byte("smf-pod-uid"), []byte(podUID)) }); err != nil {
		return err
	}
	s.mu.Lock()
	s.ready = true
	s.mu.Unlock()
	return nil
}
func (s *Server) smfPodUID(ctx context.Context) (string, error) {
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	if host == "" {
		return "", fmt.Errorf("Kubernetes API address is unavailable")
	}
	token, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
	if err != nil {
		return "", err
	}
	u := "https://" + host + ":443/api/v1/namespaces/oai-core/pods?labelSelector=oai-lab%2Fcomponent%3Dsmf"
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Authorization", "Bearer "+string(token))
	resp, err := s.kubeClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", fmt.Errorf("SMF pod lookup: %s", resp.Status)
	}
	var result struct {
		Items []struct {
			Metadata struct {
				UID string `json:"uid"`
			}
			Status struct {
				Phase string `json:"phase"`
			}
		} `json:"items"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", err
	}
	for _, p := range result.Items {
		if p.Status.Phase == "Running" && p.Metadata.UID != "" {
			return p.Metadata.UID, nil
		}
	}
	return "", fmt.Errorf("no running SMF pod")
}
func (s *Server) ReconcileLoop(ctx context.Context) {
	for {
		if err := s.Reconcile(ctx); err != nil {
			log.Printf("reconcile: %v", err)
			s.mu.Lock()
			s.ready = false
			s.mu.Unlock()
		} else {
			log.Printf("ICS producer and SMF subscription reconciled")
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(30 * time.Second):
		}
	}
}
