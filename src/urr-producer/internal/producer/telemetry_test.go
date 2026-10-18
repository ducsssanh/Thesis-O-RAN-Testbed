package producer

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"testing"
)

// Records after the cursor are published once; a producer restart resumes
// from the stored cursor; a new source_epoch (UPF restart) starts at 0.
func TestTelemetryPullCursor(t *testing.T) {
	epoch, last := "20261018T000000Z", uint64(3)
	upf := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		since, _ := strconv.ParseUint(r.URL.Query().Get("since"), 10, 64)
		recs := ""
		for q := since + 1; q <= last; q++ {
			if recs != "" {
				recs += ","
			}
			recs += fmt.Sprintf(`{"seq":%d,"supi":"imsi-1","seid":42,"time_unix":%d,"window_ms":1000,"body":{"ul_pkts":%d}}`, q, 100+q, q)
		}
		fmt.Fprintf(w, `{"source":"upf","source_epoch":"%s","enabled":true,"last_seq":%d,"gap":false,"records":[%s]}`, epoch, last, recs)
	}))
	defer upf.Close()
	dir := t.TempDir()
	cfg := Config{StateDir: dir, InfoTypeID: "oai-urr_1.0.0", ExtraTypes: []string{"oai-upf-profile_1.0.0"}, TelemetryURL: upf.URL, SUPI: "imsi-1"}
	s, err := New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	postJob(t, s, "profjob", "oai-upf-profile_1.0.0", "")
	if n, err := s.pullTelemetry(context.Background()); err != nil || n != 3 {
		t.Fatalf("first pull %d %v", n, err)
	}
	if n, _ := s.pullTelemetry(context.Background()); n != 0 {
		t.Fatalf("second pull republished %d", n)
	}
	s.Close()
	last = 5
	if s, err = New(cfg); err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	if n, _ := s.pullTelemetry(context.Background()); n != 2 {
		t.Fatalf("after restart %d, want 2", n)
	}
	epoch, last = "20261018T010000Z", 2
	if n, _ := s.pullTelemetry(context.Background()); n != 2 {
		t.Fatalf("after UPF restart %d, want 2", n)
	}
	if e, q := s.cursor(); e != epoch || q != 2 {
		t.Fatalf("cursor %s %d", e, q)
	}
	if k := pendingKeys(t, s); len(k) != 7 {
		t.Fatalf("queued %d: %v", len(k), k)
	}
}
