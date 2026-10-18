package producer

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// PDU_SES_EST becomes an oai-session record with the establishment epoch;
// the first usage report of the session adds SESSION_BOUND with its SEID;
// URR still flows; without the session type the event is rejected as before.
func TestSessionEvents(t *testing.T) {
	dir := t.TempDir()
	s, err := New(Config{StateDir: dir, InfoTypeID: "oai-urr_1.0.0", ExtraTypes: []string{"oai-session_1.0.0"}, SUPI: "imsi-1", DNN: "nist-dnn", SST: 1, SD: "FFFFFF"})
	if err != nil {
		t.Fatal(err)
	}
	defer s.Close()
	postJob(t, s, "urrjob", "oai-urr_1.0.0", "")
	postJob(t, s, "sessjob", "oai-session_1.0.0", "")
	post := func(body string) int {
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/smf", strings.NewReader(body)))
		return w.Code
	}
	if c := post(`{"notifId":"p-session","eventNotifs":[{"event":"PDU_SES_EST","pduSeId":1,"supi":"imsi-1","adIpv4Addr":"10.1.0.2","dnn":"nist-dnn","pduSessType":"IPV4","timeStamp":"3912345600"}]}`); c != 204 {
		t.Fatalf("PDU_SES_EST status %d", c)
	}
	urr := `{"notifId":"p","eventNotifs":[{"event":"QOS_MON","pduSeId":1,"supi":"imsi-1","timeStamp":"3912345678","customized_data":{"Usage Report":{"SEID":42,"UR-SEQN":1,"Duration":78,"NoP":{"Total":1,"Uplink":1,"Downlink":0},"Volume":{"Total":10,"Uplink":10,"Downlink":0}}}}]}`
	if c := post(urr); c != 204 {
		t.Fatalf("URR status %d", c)
	}
	if c := post(strings.Replace(urr, `"UR-SEQN":1`, `"UR-SEQN":2`, 1)); c != 204 {
		t.Fatalf("URR 2 status %d", c)
	}
	b, err := os.ReadFile(dir + "/envelopes.jsonl")
	if err != nil {
		t.Fatal(err)
	}
	var events []Envelope
	for _, line := range strings.Split(strings.TrimSpace(string(b)), "\n") {
		var e Envelope
		if err := json.Unmarshal([]byte(line), &e); err != nil {
			t.Fatal(err)
		}
		events = append(events, e)
	}
	if len(events) != 2 {
		t.Fatalf("want EST + one SESSION_BOUND, got %d: %s", len(events), b)
	}
	est, bound := events[0], events[1]
	if !strings.Contains(string(est.Body), `"event":"PDU_SES_EST"`) || !strings.Contains(string(est.Body), `"ue_ipv4":"10.1.0.2"`) || est.SessionEpoch != formatEpoch(3912345600-ntpUnixOffset) || est.Source != "smf" {
		t.Fatalf("EST record %+v %s", est, est.Body)
	}
	// URR epoch = smf time - Duration = the same instant as the EST here
	if !strings.Contains(string(bound.Body), `"event":"SESSION_BOUND"`) || bound.SEID != 42 || bound.SessionEpoch != est.SessionEpoch {
		t.Fatalf("SESSION_BOUND record %+v %s", bound, bound.Body)
	}
	keys := pendingKeys(t, s)
	if len(keys) != 4 {
		t.Fatalf("queue %v", keys)
	}

	s2, err := New(Config{StateDir: t.TempDir(), InfoTypeID: "oai-urr_1.0.0", SUPI: "imsi-1"})
	if err != nil {
		t.Fatal(err)
	}
	defer s2.Close()
	w := httptest.NewRecorder()
	s2.Handler().ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/callbacks/smf", strings.NewReader(`{"notifId":"x","eventNotifs":[{"event":"PDU_SES_EST","supi":"imsi-1","timeStamp":"3912345600"}]}`)))
	if w.Code != 400 {
		t.Fatalf("session event without the type: %d", w.Code)
	}
}
