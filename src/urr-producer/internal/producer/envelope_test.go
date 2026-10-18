package producer

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	bolt "go.etcd.io/bbolt"
)

func postJob(t *testing.T, s *Server, id, infoType, supi string) {
	t.Helper()
	job := `{"info_job_identity":"` + id + `","info_type_identity":"` + infoType + `","target_uri":"https://a1-ei-adapter.example/` + id + `","info_job_data":{"supi":"` + supi + `"}}`
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/ics/jobs", strings.NewReader(job)))
	if w.Code != 200 {
		t.Fatalf("job %s status %d: %s", id, w.Code, w.Body.String())
	}
}

func pendingKeys(t *testing.T, s *Server) []string {
	t.Helper()
	keys := []string{}
	_ = s.db.View(func(tx *bolt.Tx) error {
		return tx.Bucket(pendingBucket).ForEach(func(k, _ []byte) error { keys = append(keys, string(k)); return nil })
	})
	return keys
}

// Each record goes only to the jobs of its own type; a record published
// twice is queued once; URR stays on the URR job; the session epoch learnt
// from usage reports is added to the record.
func TestPublishRoutesByTypeAndDeduplicates(t *testing.T) {
	s, err := New(Config{StateDir: t.TempDir(), InfoTypeID: "oai-urr_1.0.0", ExtraTypes: []string{"oai-test_1.0.0"}, SUPI: "imsi-1", DNN: "nist-dnn", SST: 1, SD: "FFFFFF"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	postJob(t, s, "urrjob", "oai-urr_1.0.0", "")
	postJob(t, s, "testjob", "oai-test_1.0.0", "")
	postJob(t, s, "otherue", "oai-test_1.0.0", "imsi-2")
	callback := `{"notifId":"p","eventNotifs":[{"event":"QOS_MON","supi":"imsi-1","timeStamp":"3912345678","customized_data":{"Usage Report":{"SEID":42,"UR-SEQN":7,"Duration":120,"NoP":{"Total":1,"Uplink":1,"Downlink":0},"Volume":{"Total":10,"Uplink":10,"Downlink":0}}}}]}`
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/smf", strings.NewReader(callback)))
	if w.Code != 204 {
		t.Fatalf("callback status %d: %s", w.Code, w.Body.String())
	}
	e := Envelope{Type: "oai-test_1.0.0", Source: "producer-test", SourceEpoch: "20261018T000000Z", Seq: 1, SUPI: "imsi-1", TimeUnix: 1791623895, Body: json.RawMessage(`{"n":1}`)}
	for i := 0; i < 2; i++ {
		if err := s.Publish(e); err != nil {
			t.Fatal(err)
		}
	}
	keys := pendingKeys(t, s)
	if len(keys) != 2 || !strings.HasPrefix(keys[0], "testjob:oai-test_1.0.0:producer-test:20261018T000000Z:1") || !strings.HasPrefix(keys[1], "urrjob:42:") {
		t.Fatalf("unexpected queue %v", keys)
	}
	var queued pendingDelivery
	_ = s.db.View(func(tx *bolt.Tx) error { return json.Unmarshal(tx.Bucket(pendingBucket).Get([]byte(keys[0])), &queued) })
	var got Envelope
	if err := json.Unmarshal(queued.Report, &got); err != nil {
		t.Fatal(err)
	}
	if got.SEID != 42 || got.SessionEpoch == "" || got.SchemaVersion != envelopeSchema {
		t.Fatalf("record not enriched: %+v", got)
	}
	if err := s.Publish(Envelope{Type: "oai-urr_1.0.0", Source: "x", SourceEpoch: "1", Seq: 1, SUPI: "imsi-1", TimeUnix: 1, Body: json.RawMessage(`{}`)}); err == nil {
		t.Fatal("URR type must not be published as an envelope")
	}
	if err := s.Publish(Envelope{Type: "oai-test_1.0.0", Source: "a:b", SourceEpoch: "1", Seq: 1, SUPI: "imsi-1", TimeUnix: 1, Body: json.RawMessage(`{}`)}); err == nil {
		t.Fatal("a source with ':' would break the key")
	}
	w = httptest.NewRecorder()
	job := `{"info_job_identity":"x","info_type_identity":"oai-unknown_1.0.0","target_uri":"https://a/x","info_job_data":{}}`
	s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/ics/jobs", strings.NewReader(job)))
	if w.Code != 400 {
		t.Fatalf("job of an unregistered type accepted: %d", w.Code)
	}
}
