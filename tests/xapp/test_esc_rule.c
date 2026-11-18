/* Parity of the xApp's escalation by response (esc_rule.h esc_step(), called by classifier.c escalate()) with the
   offline replay (scripts/ml/esc_calib.py rule()). Input: the files of esc_calib.py --export:
     stays.csv           stay,since_ms,offered            (offered < 0: late second)
     stays_expected.csv  stay,rho,fire_ms,refS,graceS,hits,samples,overRatio,cap   (fire_ms -1: never)
   For every stay and rho the state is fresh and esc_step() runs second by second; the first second it fires must
   equal fire_ms.
   Build: gcc -O2 -I<monitor> test_esc_rule.c -lm
   Run:   ./a.out stays.csv stays_expected.csv */
#include "esc_rule.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  int stay;
  long since_ms;
  double offered;
} row_t;

int main(int argc, char **argv) {
  if (argc < 3) return 2;
  FILE *f = fopen(argv[1], "r"), *e = fopen(argv[2], "r");
  if (!f || !e) return 2;
  char line[512];
  size_t cap_rows = 1 << 16, nr = 0;
  row_t *rows = malloc(cap_rows * sizeof(*rows));
  if (!fgets(line, sizeof(line), f)) return 2; /* header */
  while (fgets(line, sizeof(line), f)) {
    if (nr == cap_rows) rows = realloc(rows, (cap_rows *= 2) * sizeof(*rows));
    if (sscanf(line, "%d,%ld,%lf", &rows[nr].stay, &rows[nr].since_ms, &rows[nr].offered) == 3) nr++;
  }
  if (!fgets(line, sizeof(line), e)) return 2;
  long cases = 0, bad = 0, fired = 0;
  while (fgets(line, sizeof(line), e)) {
    int stay, ref_s, k, n;
    double rho, grace, over, capk;
    long fire_ms;
    if (sscanf(line, "%d,%lf,%ld,%d,%lf,%d,%d,%lf,%lf", &stay, &rho, &fire_ms, &ref_s, &grace, &k, &n, &over, &capk) != 9) continue;
    unsigned char hist[32] = {0};
    int hn = 0, head = 0, ref_n = 0;
    double ref[ESC_REF_MAX], thr = 0;
    long got = -1;
    for (size_t i = 0; i < nr && got < 0; i++) {
      if (rows[i].stay != stay) continue;
      if (esc_step(hist, &hn, &head, ref, &ref_n, ref_s, capk, over, rho, k, n, rows[i].since_ms / 1000.0, grace, rows[i].offered, &thr))
        got = rows[i].since_ms;
    }
    cases++;
    fired += got >= 0;
    if (got != fire_ms) {
      bad++;
      printf("stay %d rho %.2f: expected %ld ms, esc_step %ld ms\n", stay, rho, fire_ms, got);
    }
  }
  printf("%ld cases (%ld fire), %ld differ\n", cases, fired, bad);
  free(rows);
  return bad ? 1 : 0;
}
