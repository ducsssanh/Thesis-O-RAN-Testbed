package main

import (
	"context"
	"log"
	"net/http"
	a "oai-lab/a1-ei-adapter/internal/adapter"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"
)

func env(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}
func main() {
	sst, _ := strconv.Atoi(env("SST", "1"))
	c := a.Config{Listen: env("LISTEN_ADDR", ":8443"), TLSCert: env("TLS_CERT", "/tls/tls.crt"), TLSKey: env("TLS_KEY", "/tls/tls.key"), CAFile: env("CA_FILE", "/ca/ca.crt"), StateDir: env("STATE_DIR", "/var/lib/a1-ei"), ICSURL: env("ICS_URL", "https://informationservice.non-rt-ric.svc.cluster.local:9083"), PublicURL: env("PUBLIC_URL", "https://a1-ei-adapter.near-rt-ric.svc.cluster.local:8443"), XAppURL: os.Getenv("XAPP_URL"), JobID: env("JOB_ID", "oai-urr-nearrt-ue1"), InfoTypeID: env("INFO_TYPE_ID", "oai-urr_1.0.0"), Owner: env("JOB_OWNER", "near-rt-ric/a1-ei-adapter"), SUPI: env("SUPI", "imsi-001010000000001"), DNN: env("DNN", "nist-dnn"), SST: sst, SD: env("SD", "FFFFFF")}
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
