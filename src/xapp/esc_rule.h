/* Escalation by response, relative threshold (2026-11-13): pure functions so the rule can be tested on its own
   (tests/xapp/test_esc_rule.c) against the offline simulation (scripts/ml/esc_calib.py).
   A UE at level 2 is "over" in an active second (offered UL >= ESC_ACTIVE_KBPS, counted by the UPF profile before
   the policy) when offered > max((1 + over) x cap, rho x ref), ref = median of its first ref_s active seconds at
   level 2 (its own rate when the limit came). rho 0 gives the absolute rule (> (1 + over) x cap). The threshold is
   never below the absolute one, so the relative rule can only remove or delay an escalation. */
#ifndef ESC_RULE_H
#define ESC_RULE_H

#include <stdbool.h>

#define ESC_ACTIVE_KBPS 8.0
#define ESC_REF_MAX 8

/* add an active second to the reference until ref_s seconds are kept */
static inline void esc_ref_add(double *ref, int *n, int ref_s, double offered) {
  if (offered >= ESC_ACTIVE_KBPS && *n < ref_s && *n < ESC_REF_MAX) ref[(*n)++] = offered;
}

static inline double esc_ref_median(const double *ref, int n) {
  if (n <= 0) return 0;
  double v[ESC_REF_MAX];
  for (int i = 0; i < n; i++) v[i] = ref[i];
  for (int i = 1; i < n; i++) /* insertion sort, n <= 8 */
    for (int j = i; j > 0 && v[j - 1] > v[j]; j--) {
      const double t = v[j];
      v[j] = v[j - 1];
      v[j - 1] = t;
    }
  return n % 2 ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]);
}

static inline double esc_threshold(double cap, double over, double rho, const double *ref, int n) {
  const double abs_thr = (1.0 + over) * cap, rel = rho * esc_ref_median(ref, n);
  return rel > abs_thr ? rel : abs_thr;
}

/* one second of a UE at level 2 (classifier.c escalate()): offered < 0 = late (not counted). Updates the reference
   and the ring of over/not-over active seconds; returns true when the rule fires: past the grace, this second over
   the threshold (new evidence) and k of the last n active seconds over. *thr_out: the threshold of this second. */
static inline bool esc_step(unsigned char hist[32], int *hn, int *head, double *ref, int *ref_n, int ref_s, double cap,
                            double over_ratio, double rho, int k, int n, double since_s, double grace_s, double offered,
                            double *thr_out) {
  const bool late = offered < 0;
  if (!late) esc_ref_add(ref, ref_n, ref_s, offered);
  const double thr = esc_threshold(cap, over_ratio, rho, ref, *ref_n);
  if (thr_out) *thr_out = thr;
  const bool over = !late && cap > 0 && offered > thr;
  if (!late && offered >= ESC_ACTIVE_KBPS) { /* active seconds only: an ON/OFF flood cannot dilute the count with silent seconds */
    hist[*head] = over;
    *head = (*head + 1) % 32;
    if (*hn < 32) (*hn)++;
  }
  if (since_s < grace_s) return false;
  if (!over || offered < ESC_ACTIVE_KBPS) return false; /* new evidence only: a UE that backed off does not refresh the TTL */
  int hits = 0, m = *hn < n ? *hn : n;
  for (int i = 0; i < m; i++) hits += hist[(*head - 1 - i + 64) % 32];
  return m >= n && hits >= k;
}

#endif
