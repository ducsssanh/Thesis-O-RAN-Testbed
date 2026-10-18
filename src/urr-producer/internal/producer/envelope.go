package producer

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"path/filepath"
	"sort"
	"strings"
	"time"

	bolt "go.etcd.io/bbolt"
)

// Envelope is the common record of every information type other than URR
// (docs/CLOSED-LOOP-FRAMEWORK.md 3.2). URR keeps its own format (Normalized).
// The keys SUPI + session_epoch + time_unix join it with KPM and URR at the
// xApp; (type, source, source_epoch, seq) identifies it end to end.
type Envelope struct {
	SchemaVersion string          `json:"schema_version"`
	Type          string          `json:"type"`
	Source        string          `json:"source"`
	SourceEpoch   string          `json:"source_epoch"`
	Seq           uint64          `json:"seq"`
	RunID         string          `json:"run_id"`
	ObservedAt    string          `json:"observed_at"`
	SUPI          string          `json:"supi"`
	SEID          uint64          `json:"seid,omitempty"`
	SessionEpoch  string          `json:"session_epoch,omitempty"`
	RANIdentity   *RANIdentity    `json:"ran_identity,omitempty"`
	TimeUnix      uint64          `json:"time_unix"`
	WindowMs      uint64          `json:"window_ms,omitempty"`
	DecisionID    string          `json:"decision_id,omitempty"`
	Body          json.RawMessage `json:"body"`
}

const envelopeSchema = "1.0.0"

// maxPendingExtra keeps half of the shared delivery queue for URR: a stalled
// consumer of a new type must not stop usage reports.
const maxPendingExtra = 500

// Key is the delivery and de-duplication key of the record.
func (e Envelope) Key() string {
	return fmt.Sprintf("%s:%s:%s:%d", e.Type, e.Source, e.SourceEpoch, e.Seq)
}

func token(s string, extra string) bool {
	if s == "" || len(s) > 64 {
		return false
	}
	for _, c := range s {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.ContainsRune(extra, c)) {
			return false
		}
	}
	return true
}

func (e Envelope) validate() error {
	switch {
	case !token(e.Type, "._-"):
		return errors.New("invalid type")
	case !token(e.Source, "._-"):
		return errors.New("invalid source")
	case !token(e.SourceEpoch, ""):
		return errors.New("invalid source_epoch")
	case e.Seq == 0:
		return errors.New("seq must be positive")
	case e.SUPI == "":
		return errors.New("missing supi")
	case e.TimeUnix == 0:
		return errors.New("missing time_unix")
	case len(e.Body) == 0 || !json.Valid(e.Body):
		return errors.New("invalid body")
	}
	return nil
}

// sessionRef is the latest PDU session of a SUPI seen in its usage reports.
type sessionRef struct {
	SEID  uint64
	Epoch string
}

// enrich adds what the source cannot know: the session epoch (from the
// producer's SEID table) and the RAN identity (AMF UE table), as for URR.
func (s *Server) enrich(e *Envelope) {
	s.mu.RLock()
	latest, ok := s.sessions[e.SUPI]
	s.mu.RUnlock()
	if e.SessionEpoch == "" {
		if e.SEID == 0 && ok {
			e.SEID, e.SessionEpoch = latest.SEID, latest.Epoch
		} else if e.SEID != 0 {
			if ok && latest.SEID == e.SEID {
				e.SessionEpoch = latest.Epoch
			} else if st := s.epochOf(e.SUPI, e.SEID); st != "" {
				e.SessionEpoch = st
			}
		}
	}
	if e.RANIdentity == nil {
		e.RANIdentity = s.identity(e.SUPI)
	}
}

// rememberSession records the SUPI's latest session; true when it is new.
func (s *Server) rememberSession(supi string, seid uint64, epoch string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.sessions == nil {
		s.sessions = map[string]sessionRef{}
	}
	ref := sessionRef{seid, epoch}
	if old, ok := s.sessions[supi]; ok && old == ref {
		return false
	}
	s.sessions[supi] = ref
	return true
}

// Publish queues one record for every job of its type that selects its SUPI.
// A record already published (same key) is ignored.
func (s *Server) Publish(e Envelope) error {
	if !s.hasType(e.Type) || e.Type == s.cfg.InfoTypeID {
		return fmt.Errorf("unknown information type %q", e.Type)
	}
	if e.SchemaVersion == "" {
		e.SchemaVersion = envelopeSchema
	}
	if e.RunID == "" {
		e.RunID = s.cfg.RunID
	}
	if e.ObservedAt == "" {
		e.ObservedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	if err := e.validate(); err != nil {
		return err
	}
	s.enrich(&e)
	raw, err := json.Marshal(e)
	if err != nil {
		return err
	}
	key := e.Key()
	fresh := false
	err = s.db.Update(func(tx *bolt.Tx) error {
		seen := tx.Bucket(seenBucket)
		if seen.Get([]byte(key)) != nil {
			return nil
		}
		if tx.Bucket(pendingBucket).Stats().KeyN >= maxPendingExtra {
			return fmt.Errorf("delivery queue full for %s", e.Type)
		}
		payload, err := json.Marshal(pendingDelivery{Report: raw})
		if err != nil {
			return err
		}
		if err := tx.Bucket(jobsBucket).ForEach(func(jobID, jobData []byte) error {
			var job Job
			if err := json.Unmarshal(jobData, &job); err != nil {
				return err
			}
			if job.InformationType != e.Type || !matchesSUPI(job, e.SUPI) {
				return nil
			}
			return tx.Bucket(pendingBucket).Put([]byte(string(jobID)+":"+key), payload)
		}); err != nil {
			return err
		}
		fresh = true
		return seen.Put([]byte(key), []byte{1})
	})
	if err != nil {
		return err
	}
	if fresh {
		_ = appendJSON(filepath.Join(s.cfg.StateDir, "envelopes.jsonl"), json.RawMessage(raw))
	}
	return nil
}

// TestLoop is the synthetic source of Config.TestType: one record per second
// for every UE the producer knows (AMF table or usage reports), with one
// sequence for all UEs, so a consumer can prove the path loses and
// duplicates nothing (gate CL-1).
func (s *Server) TestLoop(ctx context.Context) {
	if s.cfg.TestType == "" {
		return
	}
	epoch := time.Now().UTC().Format("20060102T150405Z")
	var seq uint64
	t := time.NewTicker(time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case now := <-t.C:
			s.mu.RLock()
			supis := []string{}
			for supi := range s.identities {
				supis = append(supis, supi)
			}
			for supi := range s.sessions {
				if _, ok := s.identities[supi]; !ok {
					supis = append(supis, supi)
				}
			}
			s.mu.RUnlock()
			sort.Strings(supis)
			for _, supi := range supis {
				seq++
				body, _ := json.Marshal(map[string]any{"generated_unix_ms": now.UnixMilli()})
				e := Envelope{Type: s.cfg.TestType, Source: "producer-test", SourceEpoch: epoch, Seq: seq, SUPI: supi, TimeUnix: uint64(now.Unix()), WindowMs: 1000, Body: body}
				if err := s.Publish(e); err != nil {
					log.Printf("test source: %v", err)
				}
			}
		}
	}
}
