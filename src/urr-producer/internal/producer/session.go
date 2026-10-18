package producer

// Session events (gate CL-2, docs/CLOSED-LOOP-FRAMEWORK.md 3.1): the SMF's
// Nsmf_EventExposure PDU_SES_EST, PDU_SES_REL and UE_IP_CH, plus two records
// of the producer itself that bind them to what the xApp already joins on:
//   SESSION_BOUND  first usage report of a new session: its SEID and
//                  session_epoch (the SMF events carry neither)
//   RAN_IDENTITY   the AMF UE NGAP ID of a SUPI changed in the AMF table,
//                  so the xApp labels KPM of a re-attached UE before the
//                  next usage report

import (
	"encoding/json"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

var smfSessionEvents = []string{"PDU_SES_EST", "PDU_SES_REL", "UE_IP_CH"}

func isSessionEvent(name string) bool {
	for _, x := range smfSessionEvents {
		if x == name {
			return true
		}
	}
	return false
}

// sessionType is the configured oai-session type, "" when off.
func (s *Server) sessionType() string {
	for _, t := range s.cfg.ExtraTypes {
		if strings.HasPrefix(t, "oai-session_") {
			return t
		}
	}
	return ""
}

func (s *Server) nextSeq(source string) uint64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.seqs == nil {
		s.seqs = map[string]uint64{}
	}
	s.seqs[source]++
	return s.seqs[source]
}

func (s *Server) allowed(supi string) bool {
	if len(s.cfg.SUPIAllow) == 0 {
		return true
	}
	for _, a := range s.cfg.SUPIAllow {
		if a == supi {
			return true
		}
	}
	return false
}

// publishSession sends one oai-session record; seid/epoch/ran left empty are
// filled by enrich from the SUPI's latest session.
func (s *Server) publishSession(source, supi, event string, at time.Time, seid uint64, epoch string, ran *RANIdentity, body map[string]any) error {
	t := s.sessionType()
	if t == "" || !s.allowed(supi) {
		return nil
	}
	body["event"] = event
	raw, err := json.Marshal(body)
	if err != nil {
		return err
	}
	e := Envelope{Type: t, Source: source, SourceEpoch: s.started, Seq: s.nextSeq(source), SUPI: supi, SEID: seid, SessionEpoch: epoch, RANIdentity: ran, TimeUnix: uint64(at.Unix()), Body: raw}
	err = s.Publish(e)
	if err != nil {
		_ = appendJSON(filepath.Join(s.cfg.StateDir, "errors.jsonl"), map[string]any{"at": time.Now().UTC(), "error": "session record: " + err.Error()})
	}
	return err
}

// sessionEvent maps one SMF event to an oai-session record. PDU_SES_EST
// opens a session whose SEID is not known yet: its epoch is the event time
// (the usage-report epoch of the same session is within epochTolerance, and
// SESSION_BOUND gives the exact one); PDU_SES_REL and UE_IP_CH refer to the
// SUPI's current session.
func (s *Server) sessionEvent(e Event) error {
	if e.SUPI == "" {
		return fmt.Errorf("%s without SUPI", e.Event)
	}
	at := time.Now()
	if ts, err := strconv.ParseInt(e.Timestamp, 10, 64); err == nil && ts > ntpUnixOffset {
		at = time.Unix(ts-ntpUnixOffset, 0)
	}
	body := map[string]any{}
	if n, err := strconv.ParseUint(e.PduSeID.String(), 10, 8); err == nil && n > 0 { // OAI QOS_MON sends 0
		body["pdu_session_id"] = n
	}
	if e.AdIPv4 != "" {
		body["ue_ipv4"] = e.AdIPv4
	}
	if e.DNN != "" {
		body["dnn"] = e.DNN
	}
	if e.PduSessType != "" {
		body["pdu_session_type"] = e.PduSessType
	}
	epoch := ""
	if e.Event == "PDU_SES_EST" {
		epoch = formatEpoch(at.Unix())
		body["epoch_source"] = "establishment"
	}
	return s.publishSession("smf", e.SUPI, e.Event, at, 0, epoch, nil, body)
}

// sessionBound tells the consumer the SEID and epoch of a session at its
// first usage report.
func (s *Server) sessionBound(v Normalized, pduSessionID string) {
	body := map[string]any{"first_ur_seqn": v.URSequence, "duration_seconds": v.DurationSeconds}
	if n, err := strconv.ParseUint(pduSessionID, 10, 8); err == nil && n > 0 { // OAI QOS_MON sends 0
		body["pdu_session_id"] = n
	}
	at := time.Now()
	if v.EndTimeUnix > 0 {
		at = time.Unix(int64(v.EndTimeUnix), 0)
	}
	_ = s.publishSession("producer", v.SUPI, "SESSION_BOUND", at, v.SEID, v.SessionEpoch, v.RANIdentity, body)
}

// identityChanged publishes RAN_IDENTITY for every SUPI whose AMF UE NGAP ID
// is new or different in the refreshed AMF table.
func (s *Server) identityChanged(old, cur map[string]RANIdentity) {
	for supi, id := range cur {
		if prev, ok := old[supi]; ok && prev.AMFUENGAPID == id.AMFUENGAPID && prev.RANUENGAPID == id.RANUENGAPID {
			continue
		}
		x := id
		_ = s.publishSession("producer", supi, "RAN_IDENTITY", time.Now(), 0, "", &x, map[string]any{})
	}
}
