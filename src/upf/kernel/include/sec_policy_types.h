/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef __SEC_POLICY_TYPES_H__
#define __SEC_POLICY_TYPES_H__

#include <linux/types.h>

/* ==========================================================================
 * Per-SUPI security policy (lab extension, not 3GPP)
 *
 * Written by the UPF Security API (control/SecurityPolicyStore.cpp):
 *   sec_policy_by_supi  IMSI (u64)  -> struct sec_policy   memory per subscriber
 *   sec_policy_by_seid  SEID (u64)  -> struct sec_policy   derived per live session
 * Read by session_lookup_ip / session_lookup_eth (sec_policy.h) before
 * PDR match, so a dropped packet never touches the PFCP rules.
 * ========================================================================== */

enum sec_action {
  SEC_ACTION_NONE      = 0,
  SEC_ACTION_MONITOR   = 1, /* count, forward */
  SEC_ACTION_RATELIMIT = 2, /* token bucket per direction, drop on empty */
  SEC_ACTION_BLOCK     = 3, /* drop UL and DL */
};

struct sec_policy {
  __u32 action; /* enum sec_action */
  __u32 level;  /* escalation level given by the xApp (informative) */
  __u64 rate_ul_bytes_s; /* RATELIMIT: 0 = no limit in this direction */
  __u64 rate_dl_bytes_s;
  __u64 burst_ul_bytes; /* RATELIMIT: bucket depth */
  __u64 burst_dl_bytes;
  __u64 expires_at_ns; /* bpf_ktime_get_ns() clock; 0 = never */
  __u64 epoch;
  /* Token bucket state, updated by XDP without locking (approximate). */
  __u64 tokens_ul;
  __u64 tokens_dl;
  __u64 last_ul_ns;
  __u64 last_dl_ns;
};

/* sec_stats_by_seid value (PERCPU_HASH, summed by userspace). */
struct sec_stats {
  __u64 drop_ul_pkts;
  __u64 drop_ul_bytes;
  __u64 drop_dl_pkts;
  __u64 drop_dl_bytes;
  __u64 seen_ul_pkts; /* packets matched by an active policy, any verdict */
  __u64 seen_ul_bytes;
  __u64 seen_dl_pkts;
  __u64 seen_dl_bytes;
  __u64 last_drop_ns;
};

/*
 * sec_profile_by_seid value (PERCPU_HASH): packet mix of the session since it
 * started, every packet with a session, any verdict. Userspace sums the CPUs
 * and sends the difference of each second (UPF telemetry, oai-upf-profile:
 * docs/CLOSED-LOOP-FRAMEWORK.md 3.1, gate CL-3). Inner IP header only.
 */
struct sec_profile {
  __u64 ul_pkts, ul_bytes, dl_pkts, dl_bytes;
  __u64 ul_tcp, ul_tcp_syn, ul_udp, ul_icmp, ul_frag, ul_dns, ul_gtp_in_gtp;
  __u64 dl_tcp, dl_tcp_syn, dl_udp, dl_icmp, dl_frag;
  /* protocol-invalid UL packets dropped by the fixed rules (CL-4) */
  __u64 ul_spoof_drop;       /* GTP-U TEID is not the session's UL tunnel */
  __u64 ul_gtp_in_gtp_drop;  /* inner UDP to port 2152 */
};

/* sec_config (ARRAY, key 0), written by userspace */
struct sec_config {
  __u32 profile_enabled;     /* count sec_profile and the destination bitmap */
  __u32 drop_spoofed;        /* UL: drop when the TEID is not the session's */
  __u32 drop_gtp_in_gtp;     /* UL: drop inner UDP to port 2152 */
  __u32 drop_unknown_ul;     /* UL: drop when no session owns the source IP */
};

/* sec_global (PERCPU_ARRAY, key 0): drops without a session */
struct sec_global {
  __u64 unknown_ul_drop_pkts;
  __u64 unknown_ul_drop_bytes;
};

#endif /* __SEC_POLICY_TYPES_H__ */
