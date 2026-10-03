package main

import (
	"context"
	"log"
	"net/http"
	p "oai-lab/urr-ei-producer/internal/producer"
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
func main() {
	sst, _ := strconv.Atoi(env("SST", "1"))
	c := p.Config{Listen: env("LISTEN_ADDR", ":8443"), TLSCert: env("TLS_CERT", "/tls/tls.crt"), TLSKey: env("TLS_KEY", "/tls/tls.key"), CAFile: env("CA_FILE", "/ca/ca.crt"), StateDir: env("STATE_DIR", "/var/lib/urr-ei"), ICSURL: env("ICS_URL", "https://informationservice.non-rt-ric.svc.cluster.local:9083"), SMFURL: env("SMF_URL", "http://oai-smf.oai-core.svc.cluster.local"), PublicURL: env("PUBLIC_URL", "https://urr-ei-producer.non-rt-ric.svc.cluster.local:8443"), InfoTypeID: env("INFO_TYPE_ID", "oai-urr_1.0.0"), ProducerID: env("PRODUCER_ID", "oai-urr-producer"), RunID: env("RUN_ID", "bootstrap"), DNN: env("DNN", "nist-dnn"), SD: env("SD", "FFFFFF"), SUPI: env("SUPI", "imsi-001010000000001"), SST: sst}
	for _, x := range strings.Split(os.Getenv("SUPI_ALLOWLIST"), ",") {
		if x = strings.TrimSpace(x); x != "" {
			c.SUPIAllow = append(c.SUPIAllow, x)
		}
	}
	c.AMFNamespace = env("AMF_NAMESPACE", "")
	s, e := p.New(c)
	if e != nil {
		log.Fatal(e)
	}
	defer s.Close()
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	go s.ReconcileLoop(ctx)
	go s.IdentityLoop(ctx)
	go s.DeliverPending(ctx)
	srv := &http.Server{Addr: c.Listen, Handler: s.Handler(), ReadHeaderTimeout: 5 * time.Second}
	go func() {
		<-ctx.Done()
		x, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		srv.Shutdown(x)
	}()
	log.Printf("listening on %s", c.Listen)
	if e = srv.ListenAndServeTLS(c.TLSCert, c.TLSKey); e != nil && e != http.ErrServerClosed {
		log.Fatal(e)
	}
}
