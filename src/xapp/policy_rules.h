#ifndef OAI_LAB_POLICY_RULES_H
#define OAI_LAB_POLICY_RULES_H
/* Escalation table of the policy layer, free of state and I/O so
   it is unit-tested on its own (tests/xapp/test_policy_rules.c).
     level 0, no probation        -> 1   suspicion
     level 0, within probation    -> peak + 1   repeat offense after the
                                         previous episode decayed (2, 3, 4)
     level >= 1                   -> unchanged (expiry refreshed), unless a
                                     capped escalation is pending and both
                                     layers now agree
   Levels >= 3 need evidence of both layers (KPM and URR) within the fusion
   window; one layer alone stops at 2, the wanted level stays pending. */
#include <stdbool.h>

#define POLICY_MAX_LEVEL 4

typedef struct {
  int level;   /* new level (never below the current one) */
  int pending; /* level wanted but capped by single-layer evidence, 0 none */
} policy_next_t;

static inline policy_next_t policy_next(int level, int peak, bool in_probation, int pending, bool both_layers) {
  int want = level == 0 ? (in_probation ? peak + 1 : 1) : (pending > level ? pending : level);
  if (want > POLICY_MAX_LEVEL) want = POLICY_MAX_LEVEL;
  if (want < 1) want = 1;
  const int cap = both_layers ? POLICY_MAX_LEVEL : 2;
  policy_next_t n = {.level = want < cap ? want : cap, .pending = 0};
  if (n.level < level) n.level = level;
  if (want > n.level) n.pending = want;
  return n;
}
#endif
