package producer

// RAN identity of each UE, so the near-RT RIC can join KPM (keyed by the
// E2SM-KPM UE ID: AMF UE NGAP ID) with URR (keyed by SUPI and SEID).
//
// No standard interface exposes the AMF UE NGAP ID <-> SUPI binding to a RIC.
// The OAI AMF prints it in its periodic "UEs' Information" statistics table;
// the producer reads that table from the AMF pod log through the Kubernetes
// API (read-only, no AMF change). This is a lab mechanism and is documented
// as non-standard (design section 8).

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type RANIdentity struct {
	AMFUENGAPID uint64 `json:"amf_ue_ngap_id"`
	RANUENGAPID uint64 `json:"ran_ue_ngap_id"`
	NRCellID    string `json:"nr_cell_id"`
	PLMN        string `json:"plmn"`
	Source      string `json:"source"`
	ObservedAt  string `json:"observed_at"`
}

// ParseAMFUETable returns the registered UEs of the last complete
// "UEs' Information" table in an OAI AMF log, keyed by SUPI ("imsi-...").
func ParseAMFUETable(r io.Reader, now time.Time) (map[string]RANIdentity, bool) {
	var last, cur map[string]RANIdentity
	in := false
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1<<20)
	for sc.Scan() {
		line := sc.Text()
		if strings.Contains(line, "UEs' Information") {
			cur, in = map[string]RANIdentity{}, true
			continue
		}
		if !in {
			continue
		}
		cols := strings.Split(line, "|")
		if len(cols) < 10 { // separator line closes the table
			if strings.Contains(line, "-----") && !strings.Contains(line, "Index") {
				last, in = cur, false
			}
			continue
		}
		f := make([]string, 0, 8)
		for _, c := range cols[1:9] {
			f = append(f, strings.TrimSpace(c))
		}
		// Index | 5GMM State | IMSI | GUTI | RAN UE NGAP ID | AMF UE NGAP ID | PLMN | Cell Id
		if f[0] == "Index" || f[2] == "-" || f[1] != "5GMM-REGISTERED" {
			continue
		}
		amf, e1 := strconv.ParseUint(strings.TrimPrefix(strings.ToLower(f[5]), "0x"), 16, 64)
		ran, e2 := strconv.ParseUint(strings.TrimPrefix(strings.ToLower(f[4]), "0x"), 16, 64)
		if e1 != nil || e2 != nil || len(f[2]) < 5 || len(f[2]) > 15 {
			continue
		}
		cur["imsi-"+f[2]] = RANIdentity{AMFUENGAPID: amf, RANUENGAPID: ran, NRCellID: f[7],
			PLMN: strings.ReplaceAll(f[6], ",", ""), Source: "amf-ue-table",
			ObservedAt: now.UTC().Format(time.RFC3339)}
	}
	return last, last != nil
}

// IdentityLoop refreshes the SUPI -> RAN identity map from the AMF log.
func (s *Server) IdentityLoop(ctx context.Context) {
	if s.cfg.AMFNamespace == "" {
		return
	}
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	for {
		if m, err := s.readAMFUETable(ctx); err != nil {
			log.Printf("AMF UE table: %v", err)
		} else if m != nil {
			s.mu.Lock()
			s.identities = m
			s.mu.Unlock()
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

func (s *Server) identity(supi string) *RANIdentity {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if id, ok := s.identities[supi]; ok {
		return &id
	}
	return nil
}

func (s *Server) kubeGet(ctx context.Context, path string) (*http.Response, error) {
	host := os.Getenv("KUBERNETES_SERVICE_HOST")
	if host == "" {
		return nil, fmt.Errorf("Kubernetes API address is unavailable")
	}
	token, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://"+host+":443"+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+string(token))
	return s.kubeClient.Do(req)
}

func (s *Server) readAMFUETable(ctx context.Context) (map[string]RANIdentity, error) {
	ns := url.PathEscape(s.cfg.AMFNamespace)
	resp, err := s.kubeGet(ctx, "/api/v1/namespaces/"+ns+"/pods?labelSelector=oai-lab%2Fcomponent%3Damf")
	if err != nil {
		return nil, err
	}
	var pods struct {
		Items []struct {
			Metadata struct{ Name string } `json:"metadata"`
			Status   struct{ Phase string } `json:"status"`
		} `json:"items"`
	}
	err = json.NewDecoder(resp.Body).Decode(&pods)
	resp.Body.Close()
	if err != nil || resp.StatusCode != 200 {
		return nil, fmt.Errorf("AMF pod lookup: %s %v", resp.Status, err)
	}
	for _, p := range pods.Items {
		if p.Status.Phase != "Running" {
			continue
		}
		resp, err = s.kubeGet(ctx, "/api/v1/namespaces/"+ns+"/pods/"+url.PathEscape(p.Metadata.Name)+"/log?container=amf&sinceSeconds=90")
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		if resp.StatusCode != 200 {
			return nil, fmt.Errorf("AMF log: %s", resp.Status)
		}
		m, ok := ParseAMFUETable(io.LimitReader(resp.Body, 32<<20), time.Now())
		if !ok {
			return nil, nil // no complete table in the window yet
		}
		return m, nil
	}
	return nil, fmt.Errorf("no running AMF pod")
}
