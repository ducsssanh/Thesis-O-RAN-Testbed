package main

import (
	"context"
	"log"
	"net/http"
	a "oai-lab/a1-ei-adapter/internal/adapter"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

// supiFilter is the EI job's SUPI filter; set but empty selects every UE of
// the slice (several UEs, plan R1)
func supiFilter() string {
	if v, ok := os.LookupEnv("SUPI"); ok {
		return v
	}
	return "imsi-001010000000001"
}

func main() {
	sst, _ := strconv.Atoi(env("SST", "1"))
	c := a.Config{Listen: env("LISTEN_ADDR", ":8443"), TLSCert: env("TLS_CERT", "/tls/tls.crt"), TLSKey: env("TLS_KEY", "/tls/tls.key"), CAFile: env("CA_FILE", "/ca/ca.crt"), StateDir: env("STATE_DIR", "/var/lib/a1-ei"), ICSURL: env("ICS_URL", "https://informationservice.non-rt-ric.svc.cluster.local:9083"), PublicURL: env("PUBLIC_URL", "https://a1-ei-adapter.near-rt-ric.svc.cluster.local:8443"), XAppURL: os.Getenv("XAPP_URL"), JobID: env("JOB_ID", "oai-urr-nearrt-ue1"), InfoTypeID: env("INFO_TYPE_ID", "oai-urr_1.0.0"), Owner: env("JOB_OWNER", "near-rt-ric/a1-ei-adapter"), SUPI: supiFilter(), DNN: env("DNN", "nist-dnn"), SST: sst, SD: env("SD", "FFFFFF")}
	// EXTRA_JOBS: closed-loop streams, "kind=jobID@infoTypeID,..."
	// (docs/CLOSED-LOOP-FRAMEWORK.md 3.3), e.g. test=oai-test-nearrt@oai-test_1.0.0
	for _, x := range strings.Split(os.Getenv("EXTRA_JOBS"), ",") {
		if x = strings.TrimSpace(x); x == "" {
			continue
		}
		kind, rest, ok1 := strings.Cut(x, "=")
		job, infoType, ok2 := strings.Cut(rest, "@")
		if !ok1 || !ok2 || kind == "" || kind == "urr" || strings.ContainsAny(kind, "|/:") || job == "" || strings.ContainsAny(job, "|/:") || infoType == "" {
			log.Fatalf("invalid EXTRA_JOBS entry %q", x)
		}
		c.Extra = append(c.Extra, a.Stream{Kind: kind, JobID: job, InfoTypeID: infoType})
	}
	s, e := a.New(c)
	if e != nil {
		log.Fatal(e)
	}
	defer s.Close()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go s.ReconcileLoop(ctx)
	go s.DeliveryLoop(ctx)
	srv := &http.Server{Addr: c.Listen, Handler: s.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		x, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		srv.Shutdown(x)
	}()
	if e = srv.ListenAndServeTLS(c.TLSCert, c.TLSKey); e != nil && e != http.ErrServerClosed {
		log.Fatal(e)
	}
}
