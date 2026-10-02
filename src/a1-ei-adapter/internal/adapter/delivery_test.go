package adapter

import (
	"context"
	"encoding/pem"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	bolt "go.etcd.io/bbolt"
)

func TestDurableDeliveryAndLargeSEID(t *testing.T) {
	var calls atomic.Int32
	receiver := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.URL.Path != "/v1/urr/events" {
			t.Errorf("path %q", r.URL.Path)
		}
		w.WriteHeader(http.StatusCreated)
	}))
	defer receiver.Close()
	cert := receiver.Certificate()
	ca := filepath.Join(t.TempDir(), "ca.crt")
	if err := os.WriteFile(ca, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: cert.Raw}), 0600); err != nil {
		t.Fatal(err)
	}
	d := t.TempDir()
	cfg := Config{StateDir: d, CAFile: ca, JobID: "job", XAppURL: receiver.URL}
	s, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	body := `{"seid":9007199254740993,"ur_seqn":2}`
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(body)))
	if w.Code != 204 {
		t.Fatalf("status %d: %s", w.Code, w.Body.String())
	}
	s.Close()
	s, err = New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go s.DeliveryLoop(ctx)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		status := httptest.NewRecorder()
		s.Handler().ServeHTTP(status, httptest.NewRequest("GET", "/v1/delivery/status", nil))
		if strings.Contains(status.Body.String(), `"delivered":1`) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if calls.Load() != 1 {
		t.Fatal("report was not delivered after adapter restart")
	}
	b, err := os.ReadFile(filepath.Join(d, "urr.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), "9007199254740993") {
		t.Fatal("SEID lost precision")
	}
	duplicate := httptest.NewRecorder()
	s.Handler().ServeHTTP(duplicate, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(body)))
	if duplicate.Code != 204 {
		t.Fatal(fmt.Sprint(duplicate.Code))
	}
	conflict := httptest.NewRecorder()
	s.Handler().ServeHTTP(conflict, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(`{"seid":9007199254740993,"ur_seqn":2,"x":1}`)))
	if conflict.Code != 409 {
		t.Fatalf("expected conflict, got %d", conflict.Code)
	}
}

func TestQueueFullDoesNotAcknowledgeNewReport(t *testing.T) {
	s, err := New(Config{StateDir: t.TempDir(), JobID: "job", XAppURL: "https://unavailable.invalid"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	err = s.db.Update(func(tx *bolt.Tx) error {
		for i := 0; i < 1000; i++ {
			if e := tx.Bucket(pending).Put([]byte(fmt.Sprint(i)), []byte(`{}`)); e != nil {
				return e
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(`{"seid":7,"ur_seqn":8}`)))
	if w.Code != 503 {
		t.Fatalf("expected 503, got %d", w.Code)
	}
	status := httptest.NewRecorder()
	s.Handler().ServeHTTP(status, httptest.NewRequest("GET", "/v1/delivery/status", nil))
	if !strings.Contains(status.Body.String(), `"queued":1000`) {
		t.Fatal(status.Body.String())
	}
}

func TestRetryAfterMissingAcknowledgement(t *testing.T) {
	var calls atomic.Int32
	receiver := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			w.WriteHeader(503)
			return
		}
		w.WriteHeader(200)
	}))
	defer receiver.Close()
	ca := filepath.Join(t.TempDir(), "ca.crt")
	if err := os.WriteFile(ca, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: receiver.Certificate().Raw}), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := New(Config{StateDir: t.TempDir(), CAFile: ca, XAppURL: receiver.URL, JobID: "job"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(`{"seid":1,"ur_seqn":7}`)))
	if w.Code != 204 {
		t.Fatal(w.Code)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go s.DeliveryLoop(ctx)
	deadline := time.Now().Add(4 * time.Second)
	for time.Now().Before(deadline) {
		status := httptest.NewRecorder()
		s.Handler().ServeHTTP(status, httptest.NewRequest("GET", "/v1/delivery/status", nil))
		if strings.Contains(status.Body.String(), `"delivered":1`) {
			break
		}
		time.Sleep(25 * time.Millisecond)
	}
	if calls.Load() != 2 {
		t.Fatalf("expected retry after 503, calls=%d", calls.Load())
	}
}

func TestUntrustedXAppKeepsReportQueued(t *testing.T) {
	receiver := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(201) }))
	defer receiver.Close()
	s, err := New(Config{StateDir: t.TempDir(), XAppURL: receiver.URL, JobID: "job"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest("POST", "/callbacks/a1-ei/results/job", strings.NewReader(`{"seid":2,"ur_seqn":3}`)))
	if w.Code != 204 {
		t.Fatal(w.Code)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	s.DeliveryLoop(ctx)
	status := httptest.NewRecorder()
	s.Handler().ServeHTTP(status, httptest.NewRequest("GET", "/v1/delivery/status", nil))
	if !strings.Contains(status.Body.String(), `"queued":1`) {
		t.Fatal(status.Body.String())
	}
}

func TestRejectPlainHTTPXApp(t *testing.T) {
	if s, err := New(Config{StateDir: t.TempDir(), XAppURL: "http://xapp:8443"}); err == nil {
		s.Close()
		t.Fatal("plain HTTP accepted")
	}
}
