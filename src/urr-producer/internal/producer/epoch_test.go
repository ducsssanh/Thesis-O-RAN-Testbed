package producer

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestAssignEpoch(t *testing.T) {
	e1, dup, s := assignEpoch(nil, 1000, 1, "a", "")
	if dup || e1 != formatEpoch(1000) {
		t.Fatalf("first report: %s %v", e1, dup)
	}
	// Same session: +1 s jitter in the start estimate keeps the epoch.
	if e, dup, next := assignEpoch(&s, 1001, 2, "b", ""); dup || e != e1 || next.LastSeq != 2 {
		t.Fatalf("jitter opened a new epoch: %s %v", e, dup)
	}
	// Retransmission: same key, same content.
	if e, dup, _ := assignEpoch(&s, 1000, 1, "a", "a"); !dup || e != e1 {
		t.Fatalf("retransmission not detected: %s %v", e, dup)
	}
	// Reused SEID: later start, UR-SEQN restarts at 1.
	e2, dup, _ := assignEpoch(&s, 1300, 1, "c", "a")
	if dup || e2 == e1 || e2 != formatEpoch(1300) {
		t.Fatalf("reused SEID not separated: %s %v", e2, dup)
	}
	// Same key, different content, same start second: still a new epoch.
	if e, dup, _ := assignEpoch(&s, 1000, 1, "z", "a"); dup || e == e1 {
		t.Fatalf("conflicting content kept the epoch: %s %v", e, dup)
	}
}

func callback(seid, seq, duration, total int, ts int64) string {
	return fmt.Sprintf(`{"notifId":"n","eventNotifs":[{"event":"QOS_MON","supi":"imsi-1","timeStamp":"%d","customized_data":{"Usage Report":{"SEID":%d,"UR-SEQN":%d,"Trigger":"Periodic Reporting","Duration":%d,"NoP":{"Total":2,"Uplink":1,"Downlink":1},"Volume":{"Total":%d,"Uplink":%d,"Downlink":0}}}}]}`, ts, seid, seq, duration, total, total)
}

func TestReusedSEIDIsNotSwallowed(t *testing.T) {
	dir := t.TempDir()
	s, err := New(Config{StateDir: dir, SUPI: "imsi-1", DNN: "d", SST: 1, SD: "FFFFFF"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	const t0 = int64(3999846830)
	posts := []string{
		callback(8, 1, 13, 100, t0), callback(8, 2, 23, 200, t0+10), callback(8, 2, 23, 200, t0+10), // retransmission
		callback(8, 3, 34, 300, t0+20),                                 // +1 s jitter
		callback(8, 1, 5, 50, t0+600), callback(8, 2, 15, 150, t0+610), // new session after SMF restart
	}
	for i, p := range posts {
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/smf", strings.NewReader(p)))
		if w.Code != 204 {
			t.Fatalf("post %d: %d %s", i, w.Code, w.Body.String())
		}
	}
	b, _ := os.ReadFile(dir + "/normalized.jsonl")
	lines := strings.Split(strings.TrimSpace(string(b)), "\n")
	if len(lines) != 5 {
		t.Fatalf("want 5 reports, got %d:\n%s", len(lines), b)
	}
	first := formatEpoch(t0 - ntpUnixOffset - 13)
	second := formatEpoch(t0 + 600 - ntpUnixOffset - 5)
	for i, l := range lines {
		want := first
		if i >= 3 {
			want = second
		}
		if !strings.Contains(l, `"session_epoch":"`+want+`"`) {
			t.Fatalf("report %d: want epoch %s: %s", i, want, l)
		}
	}
}
