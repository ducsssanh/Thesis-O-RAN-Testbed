/* Unit test of the escalation table (plan L1 step 5), independent of any
   classifier: cc -I src/flexric/examples/xApp/c/monitor tests/xapp/test_policy_rules.c && ./a.out */
#include "policy_rules.h"
#include <stdio.h>

static int fails;

static void check(const char *name, int level, int peak, bool prob, int pending, bool both, int want_level, int want_pending) {
  policy_next_t n = policy_next(level, peak, prob, pending, both);
  bool ok = n.level == want_level && n.pending == want_pending;
  if (!ok) fails++;
  printf("%-4s %-52s -> level %d pending %d (want %d/%d)\n", ok ? "ok" : "FAIL", name, n.level, n.pending, want_level, want_pending);
}

int main(void) {
  /*    name                                              lvl peak prob pend both  -> lvl pend */
  check("first offense, one layer", 0, 0, false, 0, false, 1, 0);
  check("first offense, both layers (no skip)", 0, 0, false, 0, true, 1, 0);
  check("offense after probation passed (peak stale)", 0, 3, false, 0, true, 1, 0);
  check("repeat after level 1, one layer", 0, 1, true, 0, false, 2, 0);
  check("repeat after level 2, one layer: capped", 0, 2, true, 0, false, 2, 3);
  check("repeat after level 2, both layers", 0, 2, true, 0, true, 3, 0);
  check("repeat after level 3, both layers", 0, 3, true, 0, true, 4, 0);
  check("repeat after level 3, one layer: capped", 0, 3, true, 0, false, 2, 4);
  check("repeat after level 4 stays 4", 0, 4, true, 0, true, 4, 0);
  check("attack while at level 1: refresh only", 1, 1, false, 0, true, 1, 0);
  check("attack at 2, pending 3, still one layer", 2, 2, false, 3, false, 2, 3);
  check("attack at 2, pending 3, second layer arrives", 2, 2, false, 3, true, 3, 0);
  check("attack at 3 never lowered by one-layer evidence", 3, 3, false, 0, false, 3, 0);
  check("attack at 4 stays 4", 4, 4, false, 0, false, 4, 0);
  printf("%s\n", fails ? "FAILED" : "all passed");
  return fails != 0;
}
