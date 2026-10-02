package adapter

import (
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestResultDeduplicates(t *testing.T) {
	d := t.TempDir()
	s, e := New(Config{StateDir: d})
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	s.cfg.JobID = "job"
	for i := 0; i < 2; i++ {
		r := httptest.NewRequest(http.MethodPost, "/callbacks/a1-ei/results/job", strings.NewReader(`{"seid":1,"ur_seqn":2}`))
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 204 {
			t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
		}
	}
	b, e := os.ReadFile(d + "/urr.jsonl")
	if e != nil {
		t.Fatal(e)
	}
	if string(b) != "{\"seid\":1,\"ur_seqn\":2}\n" {
		t.Fatalf("duplicate persisted: %q", b)
	}
}

func TestResultKeysBySessionEpoch(t *testing.T) {
	d := t.TempDir()
	s, e := New(Config{StateDir: d})
	if e != nil {
		t.Fatal(e)
	}
	defer s.Close()
	s.cfg.JobID = "job"
	for _, c := range []struct {
		body string
		code int
	}{
		{`{"seid":1,"session_epoch":"20261001T120000Z","ur_seqn":2,"total_bytes":5}`, 204},
		// Same SEID/UR-SEQN, other session: stored, not a conflict.
		{`{"seid":1,"session_epoch":"20261001T121000Z","ur_seqn":2,"total_bytes":9}`, 204},
		{`{"seid":1,"session_epoch":"20261001T120000Z","ur_seqn":2,"total_bytes":7}`, 409},
		{`{"seid":1,"session_epoch":"a:b","ur_seqn":2}`, 400},
	} {
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/a1-ei/results/job", strings.NewReader(c.body)))
		if w.Code != c.code {
			t.Fatalf("%s: code=%d want %d", c.body, w.Code, c.code)
		}
	}
	b, _ := os.ReadFile(d + "/urr.jsonl")
	if strings.Count(string(b), "\n") != 2 {
		t.Fatalf("want 2 stored reports: %q", b)
	}
}
