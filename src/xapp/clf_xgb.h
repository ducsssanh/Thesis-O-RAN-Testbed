#ifndef OAI_LAB_CLF_XGB_H
#define OAI_LAB_CLF_XGB_H
/* Embedded classifier of the defense (R050, scripts/ml/export_clf.py): an
   XGBoost ensemble evaluated in the xApp itself. Per UE and KPM
   second it builds the 25 inputs of the offline pipeline (15 per-second
   features of train_clf.py cur("f15") and 10 window features of
   win_summary(.., 10)), at t + delta_s (a UPF profile arriving later counts as
   missing, as offline), and runs two alarm rules on the calibrated logit:
   soft (rate limit, budget 2 false alarms per benign UE-hour) and block
   (20 of the last 30 seconds, budget 0.5). */
#include <stdbool.h>
#include <stdint.h>

#define CLF_NF 31   /* 15 per-second + 10 window (R050/R060) + 6 UL-DL coupling (f15c, E3) */
#define CLF_HIST 32

typedef struct {
  float c6[CLF_HIST], c8[CLF_HIST], c2[CLF_HIST]; /* per second: log1p core UL kbps, log1p UL pps, UL PRB / 100 */
  float c7[CLF_HIST];                             /* per second: log1p core DL kbps (coupling inputs) */
  float z[CLF_HIST];                              /* calibrated logits */
  float za[CLF_HIST];                             /* logits of ACTIVE seconds only (core UL >= 8 kbit/s), for the a<k><n> rules */
  int na, heada;
  int n, head;                                    /* ring fill, next slot */
  double cusum_soft, cusum_block;
  uint64_t last_seq;                              /* newest vector scored */
} clf_state_t;

typedef struct {
  float x[CLF_NF];
  float z;
  double soft_stat, block_stat;
  bool soft, block, late;
} clf_out_t;

int clf_load(const char *path);          /* 0 ok */
bool clf_ready(void);
int clf_nf(void);                         /* inputs of the loaded model: 25 or 31 */
const char *clf_soft_rule(void);
double clf_soft_threshold(void);
double clf_block_threshold(void);
double clf_delta_s(void);
float clf_margin(const float *x);        /* ensemble calibrated logit of one row */
/* one second of one UE: raw inputs already masked as offline (see clf_feat in
   clf_xgb.c); updates the state and fills out */
void clf_step(clf_state_t *s, const float cur15[15], clf_out_t *out);
#endif
