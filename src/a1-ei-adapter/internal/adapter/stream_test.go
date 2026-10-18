package adapter

import (
	"context"
	"encoding/json"
	"encoding/pem"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// A closed-loop record reaches the xApp at /v1/<kind>/events with the event
// ID <job>:<source>:<source_epoch>:<seq>; URR keeps its path and ID; a record
// of another type on the stream's job is rejected.
func TestExtraStreamDelivery(t *testing.T) {
	var mu sync.Mutex
	got := map[string]string{}
	receiver := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var v struct {
			EventID string `json:"event_id"`
			JobID   string `json:"job_id"`
		}
		_ = json.Unmarshal(b, &v)
		mu.Lock()
		got[r.URL.Path] = v.EventID + " " + v.JobID
		mu.Unlock()
		w.WriteHeader(http.StatusCreated)
	}))
	defer receiver.Close()
	ca := filepath.Join(t.TempDir(), "ca.crt")
	if err := os.WriteFile(ca, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: receiver.Certificate().Raw}), 0600); err != nil {
		t.Fatal(err)
	}
	d := t.TempDir()
	s, err := New(Config{StateDir: d, CAFile: ca, JobID: "urrjob", InfoTypeID: "oai-urr_1.0.0", XAppURL: receiver.URL,
		Extra: []Stream{{Kind: "test", JobID: "testjob", InfoTypeID: "oai-test_1.0.0"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	post := func(job, body string) int {
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest("POST", "/callbacks/a1-ei/results/"+job, strings.NewReader(body)))
		return w.Code
	}
	record := `{"type":"oai-test_1.0.0","source":"producer-test","source_epoch":"20261018T000000Z","seq":5,"supi":"imsi-1","time_unix":1,"body":{}}`
	if c := post("testjob", record); c != 204 {
		t.Fatalf("record status %d", c)
	}
	if c := post("testjob", record); c != 204 {
		t.Fatalf("duplicate status %d", c)
	}
	if c := post("testjob", strings.Replace(record, `"body":{}`, `"body":{"x":1}`, 1)); c != 409 {
		t.Fatalf("conflict status %d", c)
	}
	if c := post("testjob", strings.Replace(record, "oai-test_1.0.0", "oai-other_1.0.0", 1)); c != 400 {
		t.Fatalf("wrong type status %d", c)
	}
	if c := post("urrjob", `{"seid":7,"ur_seqn":1}`); c != 204 {
		t.Fatalf("URR status %d", c)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go s.DeliveryLoop(ctx)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		mu.Lock()
		n := len(got)
		mu.Unlock()
		if n == 2 {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	mu.Lock()
	defer mu.Unlock()
	if got["/v1/test/events"] != "testjob:producer-test:20261018T000000Z:5 testjob" || got["/v1/urr/events"] != "urrjob:7:1 urrjob" {
		t.Fatalf("deliveries %v", got)
	}
	if b, err := os.ReadFile(filepath.Join(d, "test.jsonl")); err != nil || strings.Count(string(b), "\n") != 1 {
		t.Fatalf("test.jsonl: %q %v", b, err)
	}
}
