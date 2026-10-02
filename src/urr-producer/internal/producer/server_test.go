package producer

import (
	"encoding/json"
	bolt "go.etcd.io/bbolt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestNormalizeOAIUsageReport(t *testing.T) {
	raw := `{"event":"QOS_MON","timeStamp":"3912345678","supi":"imsi-001010123456789","customized_data":{"SEID":42,"UR-SEQN":7,"Trigger":"Volume Threshold","Duration":120,"NoP":{"Total":30,"Uplink":10,"Downlink":20},"Volume":{"Total":3000,"Uplink":1000,"Downlink":2000}}}`
	var e Event
	if err := json.Unmarshal([]byte(raw), &e); err != nil {
		t.Fatal(err)
	}
	v, err := Normalize(e, Config{RunID: "r1", DNN: "nist-dnn", SST: 1, SD: "FFFFFF"}, time.Unix(1, 0))
	if err != nil {
		t.Fatal(err)
	}
	if v.SEID != 42 || v.URSequence != 7 || v.ULBytes != 1000 || v.DLBytes != 2000 || v.DNN != "nist-dnn" {
		t.Fatalf("unexpected: %+v", v)
	}
}
func TestRejectsMissingIdentity(t *testing.T) {
	e := Event{Event: "QOS_MON", Customized: json.RawMessage(`{"Volume":{"Total":1}}`)}
	if _, err := Normalize(e, Config{}, time.Now()); err == nil {
		t.Fatal("expected validation error")
	}
}

func TestOAICallbackNestedReportDeduplicatesAndQueues(t *testing.T) {
	dir := t.TempDir()
	s, err := New(Config{StateDir: dir, InfoTypeID: "oai-urr_1.0.0", SUPI: "imsi-001010123456789", DNN: "nist-dnn", SST: 1, SD: "FFFFFF"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	job := `{"info_job_identity":"job1","info_type_identity":"oai-urr_1.0.0","target_uri":"https://a1-ei-adapter.example/urr","info_job_data":{"supi":"imsi-001010123456789"}}`
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/ics/jobs", strings.NewReader(job)))
	if w.Code != 200 {
		t.Fatalf("job status %d: %s", w.Code, w.Body.String())
	}
	callback := `{"notifId":"oai-urr-producer","eventNotifs":[{"event":"QOS_MON","pduSeId":1,"supi":"imsi-001010123456789","timeStamp":"3912345678","customized_data":{"event":"QOS_MON","Usage Report":{"SEID":42,"UR-SEQN":7,"Trigger":"Volume Threshold","Duration":120,"NoP":{"Total":30,"Uplink":10,"Downlink":20},"Volume":{"Total":3000,"Uplink":1000,"Downlink":2000}}}}]}`
	for i := 0; i < 2; i++ {
		w = httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/smf", strings.NewReader(callback)))
		if w.Code != 204 {
			t.Fatalf("callback %d status %d: %s", i, w.Code, w.Body.String())
		}
	}
	b, err := os.ReadFile(dir + "/normalized.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(string(b), "\n") != 1 {
		t.Fatalf("expected one report: %s", b)
	}
	if err = s.db.View(func(tx *bolt.Tx) error {
		if tx.Bucket(pendingBucket).Stats().KeyN != 1 {
			t.Fatal("expected one queued delivery")
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	w = httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodDelete, "/callbacks/ics/jobs/job1", nil))
	if w.Code != 200 {
		t.Fatalf("delete job status %d: %s", w.Code, w.Body.String())
	}
	if err = s.db.View(func(tx *bolt.Tx) error {
		if tx.Bucket(pendingBucket).Stats().KeyN != 0 {
			t.Fatal("deleted job left queued deliveries")
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
}
