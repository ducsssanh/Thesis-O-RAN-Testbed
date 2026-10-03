package producer

import (
	"strings"
	"testing"
	"time"
)

const amfLog = `[2026-10-03 17:31:13.488] [amf_app] [debug] Send ITTI msg
   |-----------------------------------------------------------------------------------------------------------------------------------------------------------|
   |---------------------------------------------------------------------UEs' Information----------------------------------------------------------------------|
   |  Index |     5GMM State     |        IMSI        |        GUTI        |   RAN UE NGAP ID   |   AMF UE NGAP ID   |        PLMN        |       Cell Id      |
   |    1   |   5GMM-REGISTERED  |   001010123456780  |00101010000744796594|        0x01        |        0x0A        |       001,01       |      0000e014e     |
   |-----------------------------------------------------------------------------------------------------------------------------------------------------------|
   |---------------------------------------------------------------------UEs' Information----------------------------------------------------------------------|
   |  Index |     5GMM State     |        IMSI        |        GUTI        |   RAN UE NGAP ID   |   AMF UE NGAP ID   |        PLMN        |       Cell Id      |
   |    1   | 5GMM-DEREGISTERED  |   001010123456780  |00101010000744796594|        0x01        |        0x0A        |       001,01       |      0000e014e     |
   |    2   |   5GMM-REGISTERED  |   001010123456780  |00101010000744796595|        0x03        |        0x0C        |       001,01       |      0000e014e     |
   |    3   |   5GMM-REGISTERED  |   001010123456781  |00101010000744796596|        0x02        |        0x0B        |       001,01       |      0000e014e     |
   |-----------------------------------------------------------------------------------------------------------------------------------------------------------|
   |---------------------------------------------------------------------UEs' Information----------------------------------------------------------------------|
   |  Index |     5GMM State     |        IMSI        |        GUTI        |   RAN UE NGAP ID   |   AMF UE NGAP ID   |        PLMN        |       Cell Id      |
`

func TestParseAMFUETableUsesLastCompleteTable(t *testing.T) {
	m, ok := ParseAMFUETable(strings.NewReader(amfLog), time.Unix(0, 0))
	if !ok || len(m) != 2 {
		t.Fatalf("got %v %v", m, ok)
	}
	if m["imsi-001010123456780"].AMFUENGAPID != 0x0C || m["imsi-001010123456780"].RANUENGAPID != 3 {
		t.Fatalf("UE1: %+v", m["imsi-001010123456780"])
	}
	if m["imsi-001010123456781"].AMFUENGAPID != 0x0B || m["imsi-001010123456781"].PLMN != "00101" {
		t.Fatalf("UE2: %+v", m["imsi-001010123456781"])
	}
}

func TestParseAMFUETableWithoutTable(t *testing.T) {
	if _, ok := ParseAMFUETable(strings.NewReader("no table\n"), time.Now()); ok {
		t.Fatal("expected no table")
	}
}

func TestNormalizeAllowlistAndTimes(t *testing.T) {
	e := Event{Event: "QOS_MON", SUPI: "imsi-2", Timestamp: "3999600255",
		Customized: []byte(`{"Usage Report":{"SEID":1,"UR-SEQN":1,"Duration":1,"Start Time":3999600254,"End Time":3999600255,"Volume":{"Total":1,"Uplink":1,"Downlink":0},"NoP":{"Total":1,"Uplink":1,"Downlink":0}}}`)}
	if _, err := Normalize(e, Config{SUPIAllow: []string{"imsi-1"}}, time.Now()); err == nil {
		t.Fatal("allowlist not enforced")
	}
	v, err := Normalize(e, Config{}, time.Now())
	if err != nil || v.SUPI != "imsi-2" || v.EndTimeUnix != 3999600255-ntpUnixOffset || v.StartTimeUnix != v.EndTimeUnix-1 {
		t.Fatalf("%+v %v", v, err)
	}
}
