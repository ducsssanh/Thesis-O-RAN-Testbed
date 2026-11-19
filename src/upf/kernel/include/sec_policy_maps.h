/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef __SEC_POLICY_MAPS_H__
#define __SEC_POLICY_MAPS_H__

#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include "sec_policy_types.h"

/*
 * Owned by session_lookup_ip (sized in SessionLookupIPProgram::ConfigureMaps)
 * and shared into session_lookup_eth via bpf_map__reuse_fd.
 */

/* IMSI -> policy. Not read by XDP: the subscriber memory that userspace
 * derives sec_policy_by_seid from when a session is established. */
struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 1); /* Runtime: UPF_SEC_MAX_POLICIES */
  __type(key, __u64);
  __type(value, struct sec_policy);
} sec_policy_by_supi SEC(".maps");

/* SEID -> policy of the session's subscriber. Removed with the session. */
struct {
  __uint(type, BPF_MAP_TYPE_HASH);
  __uint(max_entries, 1); /* Runtime: MAX_PDU_SESSIONS */
  __type(key, __u64);
  __type(value, struct sec_policy);
} sec_policy_by_seid SEC(".maps");

/* SEID -> drop / match counters. Dropped packets never reach URR. */
struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_HASH);
  __uint(max_entries, 1); /* Runtime: MAX_PDU_SESSIONS */
  __type(key, __u64);
  __type(value, struct sec_stats);
} sec_stats_by_seid SEC(".maps");

/* SEID -> packet mix (struct sec_profile), PERCPU. */
struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_HASH);
  __uint(max_entries, 1); /* Runtime: MAX_PDU_SESSIONS */
  __type(key, __u64);
  __type(value, struct sec_profile);
} sec_profile_by_seid SEC(".maps");

/* SEID -> 64-bit bitmap of hashed UL destination IPs (linear counting),
 * PERCPU; userspace ORs the CPUs and clears it every second. */
struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_HASH);
  __uint(max_entries, 1); /* Runtime: MAX_PDU_SESSIONS */
  __type(key, __u64);
  __type(value, __u64);
} sec_dst_bits_by_seid SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, struct sec_config);
} sec_config SEC(".maps");

struct {
  __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
  __uint(max_entries, 1);
  __type(key, __u32);
  __type(value, struct sec_global);
} sec_global SEC(".maps");

#endif /* __SEC_POLICY_MAPS_H__ */
