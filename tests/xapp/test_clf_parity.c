/* Parity of the embedded classifier with the offline pipeline.
   Input: the model (scripts/ml/export_clf.py) and the sequences of
   scripts/ml/clf_parity_seq.py (ep, 15 per-second inputs, 25 model inputs, z
   from xgboost). For each episode the state is fresh, clf_step() runs second
   by second; the 10 window inputs and the logit are compared.
   Build: gcc -O2 -I<monitor> test_clf_parity.c <monitor>/clf_xgb.c -ljson-c -lm
   Run:   ./a.out clf_model.json seq.csv */
#include "clf_xgb.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc < 3 || clf_load(argv[1])) return 2;
  FILE *f = fopen(argv[2], "r");
  if (!f) return 2;
  char line[8192];
  clf_state_t s;
  memset(&s, 0, sizeof(s));
  double ep = -1, max_dx = 0, max_dz = 0;
  long rows = 0, bad = 0;
  while (fgets(line, sizeof(line), f)) {
    const int NF = clf_nf();
    double v[1 + 15 + CLF_NF + 1];
    char *p = line;
    for (int i = 0; i < 17 + NF; i++) v[i] = strtod(p, &p), p += *p == ',';
    if (v[0] != ep) { memset(&s, 0, sizeof(s)); ep = v[0]; }
    float cur[15];
    for (int i = 0; i < 15; i++) cur[i] = (float)v[1 + i];
    clf_out_t o;
    clf_step(&s, cur, &o);
    for (int i = 0; i < NF; i++) {
      const double d = fabs(o.x[i] - v[16 + i]);
      if (d > max_dx) max_dx = d;
    }
    if (argc > 3) { /* "direct": the trees on the reference inputs (tree walk alone) */
      float xr[CLF_NF];
      for (int i = 0; i < NF; i++) xr[i] = (float)v[16 + i];
      o.z = clf_margin(xr);
    }
    if (getenv("BLOCK_OUT") && *getenv("BLOCK_OUT")) { static FILE *bo; if (!bo) bo = fopen(getenv("BLOCK_OUT"), "w"); fprintf(bo, "%d\n", o.block ? 1 : 0); } /* block_out */
    const double dz = fabs(o.z - v[16 + NF]);
    if (dz > max_dz) max_dz = dz;
    bad += dz > 1e-3;
    rows++;
  }
  printf("rows %ld, max |dx| %.3g, max |dz| %.3g, rows with |dz| > 1e-3: %ld\n", rows, max_dx, max_dz, bad);
  return max_dz < 1e-3 ? 0 : 1;
}
