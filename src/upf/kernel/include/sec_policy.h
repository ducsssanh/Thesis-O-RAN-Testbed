/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef __SEC_POLICY_H__
#define __SEC_POLICY_H__

#include <linux/bpf.h>
#include <linux/ip.h>
#include <linux/in.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#include "packet_context.h"
#include "sec_policy_maps.h"

#define SEC_NSEC_PER_SEC 1000000000ULL

/* Refill and take len bytes. Returns 1 if the packet fits. */
static __always_inline int sec_bucket_take(
    __u64* tokens, __u64* last_ns, __u64 rate, __u64 burst, __u64 now,
    __u64 len) {
  if (rate == 0) return 1;

  __u64 elapsed = now - *last_ns;
  if (elapsed > SEC_NSEC_PER_SEC) elapsed = SEC_NSEC_PER_SEC;
  __u64 add = elapsed * rate / SEC_NSEC_PER_SEC;
  __u64 t   = *tokens;
  /* Keep the remainder when the refill rounds to 0 bytes */
  if (add) {
    t += add;
    if (t > burst) t = burst;
    *last_ns = now;
  }
  if (t < len) {
    *tokens = t;
    return 0;
  }
  *tokens = t - len;
  return 1;
}

/*
 * UL packet with an inner source IP that no session owns (session lookup
 * failed). Upstream passes it to the kernel; with drop_unknown_ul it is
 * dropped and counted (CL-4). Returns 1 to drop.
 */
static __always_inline int sec_unknown_ul(
    struct xdp_md* ctx, struct packet_context* pctx) {
  __u32 zero_key       = 0;
  struct sec_config* c = bpf_map_lookup_elem(&sec_config, &zero_key);
  if (!c || !c->drop_unknown_ul || !IS_UPLINK(pctx->session_type)) return 0;
  struct sec_global* g = bpf_map_lookup_elem(&sec_global, &zero_key);
  if (g) {
    g->unknown_ul_drop_pkts++;
    g->unknown_ul_drop_bytes += ctx->data_end - ctx->data;
  }
  return 1;
}

/*
 * Packet mix of the session (struct sec_profile), counted before the policy so
 * dropped packets are evidence too. IP PDU only: the inner IPv4 header is at
 * pctx->inner_l3_off (UL: after GTP-U; DL: the packet's own header).
 * Also the fixed protocol rules (CL-4, no parameter): UL with a TEID that is
 * not the session's UL tunnel (source address of another UE), UL inner UDP to
 * the GTP-U port. Returns 1 to drop.
 */
static __always_inline int sec_profile_count(
    struct xdp_md* ctx, struct packet_context* pctx, __u64 len, int ul) {
  __u32 zero_key       = 0;
  struct sec_config* c = bpf_map_lookup_elem(&sec_config, &zero_key);
  if (!c || !IS_IP_PDU(pctx->session_type)) return 0;
  int spoofed = ul && c->drop_spoofed && pctx->teid_ul &&
                pctx->pkt_teid != pctx->teid_ul;
  if (!c->profile_enabled && !spoofed && !c->drop_gtp_in_gtp) return 0;

  __u64 seid             = pctx->seid;
  struct sec_profile* pr = bpf_map_lookup_elem(&sec_profile_by_seid, &seid);
  if (!pr) {
    struct sec_profile zero = {};
    bpf_map_update_elem(&sec_profile_by_seid, &seid, &zero, BPF_NOEXIST);
    pr = bpf_map_lookup_elem(&sec_profile_by_seid, &seid);
    if (!pr) return spoofed;
  }
  if (spoofed) {
    pr->ul_spoof_drop++;
    return 1;
  }
  /* PERCPU + softirq context: no atomics needed */
  if (ul) {
    pr->ul_pkts++;
    pr->ul_bytes += len;
  } else {
    pr->dl_pkts++;
    pr->dl_bytes += len;
  }

  void* data     = (void*) (long) ctx->data;
  void* data_end = (void*) (long) ctx->data_end;
  __u32 off      = pctx->inner_l3_off & 0x1ff;
  if (!off) return 0;
  struct iphdr* ip = data + off;
  if ((void*) (ip + 1) > data_end || ip->version != 4) return 0;
  __u32 ihl = ip->ihl * 4;
  if (ihl < sizeof(*ip)) return 0;
  int drop = 0;

  __u16 frag = ip->frag_off & bpf_htons(0x3fff); /* MF or offset */
  if (frag) {
    if (ul)
      pr->ul_frag++;
    else
      pr->dl_frag++;
  }
  int first = !(ip->frag_off & bpf_htons(0x1fff)); /* L4 header present */
  void* l4  = (void*) ip + ihl;

  if (ip->protocol == IPPROTO_TCP) {
    int syn = 0;
    struct tcphdr* th = l4;
    if (first && (void*) (th + 1) <= data_end) syn = th->syn && !th->ack;
    if (ul) {
      pr->ul_tcp++;
      pr->ul_tcp_syn += syn;
    } else {
      pr->dl_tcp++;
      pr->dl_tcp_syn += syn;
    }
  } else if (ip->protocol == IPPROTO_UDP) {
    struct udphdr* uh = l4;
    if (ul) {
      pr->ul_udp++;
      if (first && (void*) (uh + 1) <= data_end) {
        if (uh->dest == bpf_htons(53)) pr->ul_dns++;
        if (uh->dest == bpf_htons(2152)) {
          pr->ul_gtp_in_gtp++;
          if (c->drop_gtp_in_gtp) {
            pr->ul_gtp_in_gtp_drop++;
            drop = 1;
          }
        }
      }
    } else {
      pr->dl_udp++;
    }
  } else if (ip->protocol == IPPROTO_ICMP) {
    if (ul)
      pr->ul_icmp++;
    else
      pr->dl_icmp++;
  }

  if (ul) {
    /* destination set of the window: one bit of a 64-bit bitmap per hashed
     * IP (linear counting in userspace) */
    __u32 h       = bpf_ntohl(ip->daddr) * 2654435761u;
    __u64 bit     = 1ULL << (h >> 26);
    __u64* bits   = bpf_map_lookup_elem(&sec_dst_bits_by_seid, &seid);
    if (bits) {
      *bits |= bit;
    } else {
      bpf_map_update_elem(&sec_dst_bits_by_seid, &seid, &bit, BPF_NOEXIST);
    }
  }
  return drop;
}

/*
 * Per-SUPI security stage, inline at the end of session lookup (SEID known,
 * PFCP rules not yet touched). No entry or expired entry: one lookup, pass.
 * Returns 1 to drop the packet.
 */
static __always_inline int sec_policy_apply(
    struct xdp_md* ctx, struct packet_context* pctx) {
  __u64 seid = pctx->seid;
  __u64 len  = ctx->data_end - ctx->data;
  int ul     = IS_UPLINK(pctx->session_type);
  if (sec_profile_count(ctx, pctx, len, ul)) return 1;

  struct sec_policy* p = bpf_map_lookup_elem(&sec_policy_by_seid, &seid);
  if (!p) return 0;

  __u32 action = p->action;
  if (action == SEC_ACTION_NONE) return 0;
  __u64 now = bpf_ktime_get_ns();
  if (p->expires_at_ns && now >= p->expires_at_ns) return 0;

  int drop  = 0;
  if (action == SEC_ACTION_BLOCK) {
    drop = 1;
  } else if (action == SEC_ACTION_RATELIMIT) {
    if (ul)
      drop = !sec_bucket_take(
          &p->tokens_ul, &p->last_ul_ns, p->rate_ul_bytes_s, p->burst_ul_bytes,
          now, len);
    else
      drop = !sec_bucket_take(
          &p->tokens_dl, &p->last_dl_ns, p->rate_dl_bytes_s, p->burst_dl_bytes,
          now, len);
  }

  struct sec_stats* st = bpf_map_lookup_elem(&sec_stats_by_seid, &seid);
  if (!st) {
    struct sec_stats zero = {};
    bpf_map_update_elem(&sec_stats_by_seid, &seid, &zero, BPF_NOEXIST);
    st = bpf_map_lookup_elem(&sec_stats_by_seid, &seid);
  }
  if (st) {
    /* PERCPU + softirq context: no atomics needed */
    if (ul) {
      st->seen_ul_pkts++;
      st->seen_ul_bytes += len;
      if (drop) {
        st->drop_ul_pkts++;
        st->drop_ul_bytes += len;
      }
    } else {
      st->seen_dl_pkts++;
      st->seen_dl_bytes += len;
      if (drop) {
        st->drop_dl_pkts++;
        st->drop_dl_bytes += len;
      }
    }
    if (drop) st->last_drop_ns = now;
  }
  return drop;
}

#endif /* __SEC_POLICY_H__ */
