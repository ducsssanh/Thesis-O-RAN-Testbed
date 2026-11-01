package producer

// UPF telemetry pull (gate CL-3, docs/CLOSED-LOOP-FRAMEWORK.md 3.3): the
// producer reads the UPF's record ring with a cursor once per second and
// publishes each record as oai-upf-profile. The UPF knows nothing of the
// producer; a producer restart resumes from the stored cursor, a UPF restart
// shows as a new source_epoch and restarts the cursor at 0.

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	bolt "go.etcd.io/bbolt"
)

type telemetryRecord struct {
	Seq      uint64          `json:"seq"`
	SUPI     string          `json:"supi"`
	SEID     uint64          `json:"seid"`
	TimeUnix uint64          `json:"time_unix"`
	WindowMs uint64          `json:"window_ms"`
	Body     json.RawMessage `json:"body"`
}

type telemetryPage struct {
	Source      string            `json:"source"`
	SourceEpoch string            `json:"source_epoch"`
	Enabled     bool              `json:"enabled"`
	LastSeq     uint64            `json:"last_seq"`
	Gap         bool              `json:"gap"`
	Records     []telemetryRecord `json:"records"`
}

var cursorKey = []byte("upf-telemetry-cursor")
var eventCursorKey = []byte("upf-event-cursor")

// eventType is the configured oai-upf-event type, "" when off.
func (s *Server) eventType() string {
	for _, t := range s.cfg.ExtraTypes {
		if strings.HasPrefix(t, "oai-upf-event_") {
			return t
		}
	}
	return ""
}

// profileType is the configured oai-upf-profile type, "" when off.
func (s *Server) profileType() string {
	for _, t := range s.cfg.ExtraTypes {
		if strings.HasPrefix(t, "oai-upf-profile_") {
			return t
		}
	}
	return ""
}

func (s *Server) cursor() (string, uint64) {
	var raw string
	_ = s.db.View(func(tx *bolt.Tx) error {
		raw = string(tx.Bucket(stateBucket).Get(cursorKey))
		return nil
	})
	epoch, seq, _ := strings.Cut(raw, "|")
	n, _ := strconv.ParseUint(seq, 10, 64)
	return epoch, n
}

func (s *Server) setCursor(epoch string, seq uint64) {
	_ = s.db.Update(func(tx *bolt.Tx) error {
		return tx.Bucket(stateBucket).Put(cursorKey, []byte(fmt.Sprintf("%s|%d", epoch, seq)))
	})
}

func (s *Server) fetchTelemetry(ctx context.Context, since uint64) (*telemetryPage, error) {
	u := fmt.Sprintf("%s?since=%d&limit=1000", s.cfg.TelemetryURL, since)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	c := &http.Client{Timeout: 5 * time.Second} // plain HTTP inside the cluster (UPF API, lab limitation)
	resp, err := c.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("UPF telemetry: %s", resp.Status)
	}
	var p telemetryPage
	if err := json.NewDecoder(resp.Body).Decode(&p); err != nil {
		return nil, err
	}
	return &p, nil
}

// pullTelemetry publishes the records after the cursor; returns how many.
func (s *Server) pullTelemetry(ctx context.Context) (int, error) {
	epoch, since := s.cursor()
	p, err := s.fetchTelemetry(ctx, since)
	if err != nil {
		return 0, err
	}
	if p.SourceEpoch == "" || !p.Enabled {
		return 0, nil
	}
	if p.SourceEpoch != epoch { // UPF restarted: its sequence starts again
		if since != 0 {
			log.Printf("UPF telemetry: new source_epoch %s (was %s), cursor reset", p.SourceEpoch, epoch)
		}
		s.setCursor(p.SourceEpoch, 0)
		if p, err = s.fetchTelemetry(ctx, 0); err != nil {
			return 0, err
		}
		epoch, since = p.SourceEpoch, 0
	}
	if p.Gap {
		_ = appendJSON(s.cfg.StateDir+"/errors.jsonl", map[string]any{"at": time.Now().UTC(), "error": fmt.Sprintf("UPF telemetry gap after seq %d (ring overrun)", since)})
	}
	n := 0
	for _, r := range p.Records {
		if !s.allowed(r.SUPI) {
			s.setCursor(epoch, r.Seq)
			continue
		}
		e := Envelope{Type: s.profileType(), Source: "upf", SourceEpoch: epoch, Seq: r.Seq, SUPI: r.SUPI, SEID: r.SEID, TimeUnix: r.TimeUnix, WindowMs: r.WindowMs, Body: r.Body}
		if err := s.Publish(e); err != nil {
			return n, err // queue full: retry from here next time
		}
		s.setCursor(epoch, r.Seq)
		n++
	}
	return n, nil
}

// pullStream publishes the records after a cursor from one UPF ring (profiles
// or events); shared by the two loops. url is the ring endpoint, cursorK the
// stored cursor, typ the EI type to publish as.
func (s *Server) pullStream(ctx context.Context, baseURL, typ string, cursorK []byte) (int, error) {
	readCursor := func() (string, uint64) {
		var raw string
		_ = s.db.View(func(tx *bolt.Tx) error { raw = string(tx.Bucket(stateBucket).Get(cursorK)); return nil })
		ep, seq, _ := strings.Cut(raw, "|")
		n, _ := strconv.ParseUint(seq, 10, 64)
		return ep, n
	}
	writeCursor := func(ep string, seq uint64) {
		_ = s.db.Update(func(tx *bolt.Tx) error {
			return tx.Bucket(stateBucket).Put(cursorK, []byte(fmt.Sprintf("%s|%d", ep, seq)))
		})
	}
	fetch := func(since uint64) (*telemetryPage, error) {
		u := fmt.Sprintf("%s?since=%d&limit=1000", baseURL, since)
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
		if err != nil {
			return nil, err
		}
		c := &http.Client{Timeout: 5 * time.Second}
		resp, err := c.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if resp.StatusCode != 200 {
			return nil, fmt.Errorf("UPF %s: %s", typ, resp.Status)
		}
		var pg telemetryPage
		return &pg, json.NewDecoder(resp.Body).Decode(&pg)
	}
	epoch, since := readCursor()
	pg, err := fetch(since)
	if err != nil {
		return 0, err
	}
	if pg.SourceEpoch == "" || !pg.Enabled {
		return 0, nil
	}
	if pg.SourceEpoch != epoch {
		writeCursor(pg.SourceEpoch, 0)
		if pg, err = fetch(0); err != nil {
			return 0, err
		}
		epoch, since = pg.SourceEpoch, 0
	}
	_ = since
	n := 0
	for _, r := range pg.Records {
		if !s.allowed(r.SUPI) {
			writeCursor(epoch, r.Seq)
			continue
		}
		e := Envelope{Type: typ, Source: "upf", SourceEpoch: epoch, Seq: r.Seq, SUPI: r.SUPI, SEID: r.SEID, TimeUnix: r.TimeUnix, WindowMs: r.WindowMs, Body: r.Body}
		if err := s.Publish(e); err != nil {
			return n, err
		}
		writeCursor(epoch, r.Seq)
		n++
	}
	return n, nil
}

// upfTickLag: the UPF closes each 1 s window 20 ms after the wall-clock second
// (SecurityPolicyStore::TelemetryLoop); pulling just after that tick, not on a
// free-running ticker, saves up to 1 s of waiting per record.
const upfTickLag = 80 * time.Millisecond

func untilUPFTick() time.Duration {
	now := time.Now()
	next := now.Truncate(time.Second).Add(upfTickLag)
	if !next.After(now) {
		next = next.Add(time.Second)
	}
	return next.Sub(now)
}

// EventLoop pulls the UPF event ring every second while oai-upf-event is on.
func (s *Server) EventLoop(ctx context.Context) {
	typ := s.eventType()
	if typ == "" || s.cfg.EventsURL == "" {
		return
	}
	failing := false
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(untilUPFTick()):
		}
		_, err := s.pullStream(ctx, s.cfg.EventsURL, typ, eventCursorKey)
		if err != nil && !failing {
			log.Printf("UPF events: %v", err)
		}
		failing = err != nil
	}
}

// TelemetryLoop pulls the UPF ring every second while oai-upf-profile is on.
func (s *Server) TelemetryLoop(ctx context.Context) {
	if s.profileType() == "" || s.cfg.TelemetryURL == "" {
		return
	}
	failing := false
	for {
		select {
		case <-ctx.Done():
			return
		case <-time.After(untilUPFTick()):
		}
		_, err := s.pullTelemetry(ctx)
		if err != nil && !failing {
			log.Printf("UPF telemetry: %v", err)
		} else if err == nil && failing {
			log.Printf("UPF telemetry: recovered")
		}
		failing = err != nil
	}
}
