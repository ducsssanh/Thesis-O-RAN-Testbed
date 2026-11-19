/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef SECURITY_POLICY_STORE_H_
#define SECURITY_POLICY_STORE_H_

/**
 * @file SecurityPolicyStore.h
 * @brief Per-SUPI security policy of the UPF (lab extension, not 3GPP).
 *
 * The xApp decides; the UPF remembers and enforces. Source of truth is a
 * SQLite DB on the pod's PersistentVolume; sec_policy_by_supi mirrors it in
 * BPF, and sec_policy_by_seid is derived for every live session of the
 * subscriber (sec_policy.h applies it in XDP before PDR match).
 *
 * All limits come from the environment (chart: global.lab.defense.upfSecurity):
 *   UPF_SEC_ENABLED, UPF_SEC_PORT, UPF_SEC_DB_PATH, UPF_SEC_AUDIT_PATH,
 *   UPF_SEC_MAX_TTL_S, UPF_SEC_MAX_CMDS_PER_S, UPF_SEC_MAX_BLOCKED_RATIO,
 *   UPF_SEC_MAX_POLICIES, UPF_SEC_RATELIMIT_BURST_MS, UPF_SEC_SWEEP_S,
 *   UPF_SEC_PROFILE, UPF_SEC_TELEMETRY_RING
 *
 * Telemetry (gate CL-3, docs/CLOSED-LOOP-FRAMEWORK.md 3.3): every second the
 * packet mix of each live session (sec_profile_by_seid) is differenced into
 * one record of a ring; the urr-ei-producer pulls the ring with a cursor
 * (GET /v1/telemetry?since=<seq>) and publishes it as oai-upf-profile.
 */

#include <cstdint>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <atomic>
#include <condition_variable>

#include <nlohmann/json.hpp>

#include "sec_policy_types.h"

class BPFMap;
struct sqlite3;

struct SecurityConfig {
  bool enabled              = false;
  uint16_t port             = 8095;
  std::string db_path       = "/upf-sec/sec_policy.db";
  std::string audit_path    = "/upf-sec/audit.jsonl";
  uint32_t max_ttl_s        = 86400;
  uint32_t max_cmds_per_s   = 10;
  double max_blocked_ratio  = 0.5;
  uint32_t max_policies     = 16384;
  uint32_t ratelimit_burst_ms = 100;
  uint32_t sweep_s          = 5;
  bool profile              = true;   // count sec_profile in XDP + telemetry
  uint32_t telemetry_ring   = 7200;   // records kept for the pull cursor
  /* fixed protocol rules in XDP (CL-4), each with its own switch */
  bool drop_spoofed         = true;   // UL TEID is not the session's tunnel
  bool drop_gtp_in_gtp      = true;   // UL inner UDP to port 2152
  bool drop_unknown_ul      = true;   // UL source IP owned by no session
  /* volume-quota reflex (CL-4): UPF's own response to a UL flood, uplink
   * only. "off" = detect and report, never act; "ratelimit" = also limit */
  std::string reflex_mode   = "off";  // off | ratelimit
  uint64_t reflex_quota_ul_bytes = 3125000;  // UL bytes/s over which it trips (25 Mbit/s)
  uint64_t reflex_rate_ul_kbps   = 2000;     // ratelimit applied by the reflex
  uint32_t reflex_ttl_s     = 10;     // expires unless the xApp confirms
  uint32_t reflex_ttl_max_s = 60;     // repeated trips double the TTL up to this
  double reflex_max_share   = 0.2;    // at most this share of live sessions under a reflex

  static const SecurityConfig& Get();
};

struct SecPolicyRecord {
  std::string supi;  // "imsi-<digits>"
  std::string action;
  uint64_t rate_ul_kbps = 0;
  uint64_t rate_dl_kbps = 0;
  int64_t expires_at_ms = 0;  // wall clock (DB survives restarts)
  uint64_t epoch        = 0;
  uint32_t level        = 0;
  int64_t updated_at_ms = 0;
};

class SecurityPolicyStore {
 public:
  struct Reply {
    int status;
    nlohmann::json body;
  };

  static SecurityPolicyStore& GetInstance();

  /** Open the DB, load the policies into sec_policy_by_supi, start sweeping. */
  bool Start(
      std::shared_ptr<BPFMap> by_supi, std::shared_ptr<BPFMap> by_seid,
      std::shared_ptr<BPFMap> stats);
  void Stop();
  bool Running() const { return running_; }

  /** Packet-mix telemetry (after Start): enable counting, start the 1 s loop. */
  bool StartTelemetry(
      std::shared_ptr<BPFMap> profile, std::shared_ptr<BPFMap> dst_bits,
      std::shared_ptr<BPFMap> config, std::shared_ptr<BPFMap> global);
  /** Records with seq > since (at most limit), oldest first. */
  nlohmann::json Telemetry(uint64_t since, size_t limit);
  /** Rule trips and reflexes with seq > since (oai-upf-event). */
  nlohmann::json Events(uint64_t since, size_t limit);
  /** Change reflex parameters at runtime (the xApp's rule parameters). */
  Reply PutConfig(const std::string& body, const std::string& peer);
  nlohmann::json ReflexConfig();

  /** Before the session pipeline is created: derive sec_policy_by_seid. */
  void OnSessionEstablished(uint64_t seid, const std::string& supi);
  /** After the session pipeline is removed: drop by_seid and stats. */
  void OnSessionRemoved(uint64_t seid);

  /* API operations (SecurityApi) */
  Reply Put(
      const std::string& supi, const std::string& body,
      const std::string& peer);
  Reply Delete(const std::string& supi, const std::string& peer);
  Reply Get(const std::string& supi);
  nlohmann::json List();
  nlohmann::json Stats(const std::string& supi);
  nlohmann::json Sessions();
  nlohmann::json Info();

 private:
  SecurityPolicyStore() = default;
  ~SecurityPolicyStore();

  bool OpenDb();
  bool DbUpsert(const SecPolicyRecord& r);
  bool DbDelete(const std::string& supi);
  void Audit(
      const std::string& op, const std::string& supi, int status,
      const nlohmann::json& detail, const std::string& peer);

  bool ActiveLocked(const SecPolicyRecord& r, int64_t now_ms) const;
  struct sec_policy ToKernel(const SecPolicyRecord& r) const;
  void ApplyLocked(const SecPolicyRecord& r);
  void ClearLocked(const std::string& supi);
  void WriteSeidLocked(uint64_t seid, const struct sec_policy& p);
  bool ReadStatsLocked(uint64_t seid, struct sec_stats& sum) const;
  nlohmann::json RecordJsonLocked(const SecPolicyRecord& r) const;
  void SweepLoop();
  void TelemetryLoop();
  nlohmann::json UnknownUlDropsLocked() const;
  void EvaluateReflexLocked(const std::string& supi, uint64_t seid, uint64_t ul_bytes_window, int64_t end_unix, int64_t now);
  void ExpireReflexesLocked(int64_t now);
  void PushEventLocked(const nlohmann::json& ev);
  void TelemetryTick(int64_t end_unix);

  mutable std::mutex mtx_;
  std::atomic<bool> running_{false};
  sqlite3* db_ = nullptr;
  int fd_by_supi_ = -1, fd_by_seid_ = -1, fd_stats_ = -1;
  std::shared_ptr<BPFMap> by_supi_, by_seid_, stats_;
  int ncpus_ = 1;
  std::string boot_id_;
  int64_t started_at_ms_ = 0;

  std::map<std::string, SecPolicyRecord> policies_;
  std::unordered_map<uint64_t, std::string> seid_supi_;  // live sessions
  std::map<std::string, struct sec_stats> closed_stats_;  // ended sessions
  std::deque<int64_t> cmd_times_ms_;

  std::thread sweeper_;
  std::condition_variable sweep_cv_;

  /* telemetry: own lock, so the API and policy paths never wait for it */
  int fd_profile_ = -1, fd_dst_bits_ = -1, fd_global_ = -1;
  std::shared_ptr<BPFMap> global_;
  std::shared_ptr<BPFMap> profile_, dst_bits_, config_;
  std::mutex tel_mtx_;
  std::deque<nlohmann::json> tel_ring_;
  uint64_t tel_seq_ = 0;
  std::string tel_epoch_;  // source_epoch: start of this UPF process (UTC)
  std::unordered_map<uint64_t, struct sec_profile> tel_last_;  // per SEID

  /* reflex (CL-4): ephemeral, in memory only (never the DB); an xApp policy
   * always wins and clears it */
  struct Reflex {
    uint64_t seid;
    int64_t expires_at_ms;
    uint32_t ttl_s;      // current TTL (doubles on repeat)
    int64_t last_trip_ms;
  };
  /* runtime reflex parameters (defaults from SecurityConfig; the xApp or the
   * gate changes them at runtime via PUT /v1/config, no restart) */
  std::string rx_mode_;
  uint64_t rx_quota_ul_bytes_ = 0;
  uint64_t rx_rate_ul_kbps_   = 0;
  uint32_t rx_ttl_s_ = 0, rx_ttl_max_s_ = 0;
  double rx_max_share_ = 0;
  std::map<std::string, Reflex> reflexes_;  // SUPI -> reflex
  std::deque<nlohmann::json> event_ring_;   // trips and reflexes (oai-upf-event)
  uint64_t event_seq_ = 0;
  std::thread telemetry_;
  std::atomic<bool> tel_running_{false};
};

#endif  // SECURITY_POLICY_STORE_H_
