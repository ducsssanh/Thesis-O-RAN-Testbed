/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#include "SecurityPolicyStore.h"

#include <bpf/bpf.h>
#include <bpf/libbpf.h>
#include <sqlite3.h>
#include <sys/stat.h>
#include <time.h>
#include <inttypes.h>

#include <algorithm>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <thread>
#include <cstdlib>
#include <fstream>
#include <set>
#include <vector>

#include "common_root_types.h"
#include "logger.hpp"
#include "wrappers/BPFMap.hpp"

using json = nlohmann::json;

namespace {

int64_t WallMs() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// Same clock as bpf_ktime_get_ns()
uint64_t MonoNs() {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t) ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

std::string EnvStr(const char* name, const std::string& def) {
  const char* v = std::getenv(name);
  return (v && *v) ? std::string(v) : def;
}

uint64_t EnvU64(const char* name, uint64_t def) {
  const char* v = std::getenv(name);
  if (!v || !*v) return def;
  char* end = nullptr;
  unsigned long long x = std::strtoull(v, &end, 10);
  return (end && *end == '\0') ? x : def;
}

double EnvDouble(const char* name, double def) {
  const char* v = std::getenv(name);
  if (!v || !*v) return def;
  char* end = nullptr;
  double x  = std::strtod(v, &end);
  return (end && *end == '\0') ? x : def;
}

bool EnvBool(const char* name, bool def) {
  std::string v = EnvStr(name, "");
  if (v.empty()) return def;
  return v == "1" || v == "true" || v == "yes" || v == "on";
}

// "imsi-<5..15 digits>" -> IMSI as integer (sec_policy_by_supi key)
bool ParseSupi(const std::string& supi, uint64_t& imsi) {
  if (supi.rfind("imsi-", 0) != 0) return false;
  std::string d = supi.substr(5);
  if (d.size() < 5 || d.size() > 15) return false;
  if (!std::all_of(d.begin(), d.end(), ::isdigit)) return false;
  imsi = std::stoull(d);
  return true;
}

uint32_t ActionCode(const std::string& a) {
  if (a == "block") return SEC_ACTION_BLOCK;
  if (a == "ratelimit") return SEC_ACTION_RATELIMIT;
  if (a == "monitor") return SEC_ACTION_MONITOR;
  return SEC_ACTION_NONE;
}

void MkdirParent(const std::string& path) {
  auto pos = path.rfind('/');
  if (pos == std::string::npos || pos == 0) return;
  std::string dir = path.substr(0, pos);
  for (size_t i = 1; i <= dir.size(); i++) {
    if (i == dir.size() || dir[i] == '/') {
      std::string p = dir.substr(0, i);
      if (mkdir(p.c_str(), 0755) != 0 && errno != EEXIST) return;
    }
  }
}

json StatsJson(const struct sec_stats& s) {
  return {{"drop_ul_pkts", s.drop_ul_pkts},   {"drop_ul_bytes", s.drop_ul_bytes},
          {"drop_dl_pkts", s.drop_dl_pkts},   {"drop_dl_bytes", s.drop_dl_bytes},
          {"seen_ul_pkts", s.seen_ul_pkts},   {"seen_ul_bytes", s.seen_ul_bytes},
          {"seen_dl_pkts", s.seen_dl_pkts},   {"seen_dl_bytes", s.seen_dl_bytes},
          {"last_drop_ns", s.last_drop_ns}};
}

void AddStats(struct sec_stats& a, const struct sec_stats& b) {
  a.drop_ul_pkts += b.drop_ul_pkts;
  a.drop_ul_bytes += b.drop_ul_bytes;
  a.drop_dl_pkts += b.drop_dl_pkts;
  a.drop_dl_bytes += b.drop_dl_bytes;
  a.seen_ul_pkts += b.seen_ul_pkts;
  a.seen_ul_bytes += b.seen_ul_bytes;
  a.seen_dl_pkts += b.seen_dl_pkts;
  a.seen_dl_bytes += b.seen_dl_bytes;
  a.last_drop_ns = std::max(a.last_drop_ns, b.last_drop_ns);
}

}  // namespace

//------------------------------------------------------------------------------
const SecurityConfig& SecurityConfig::Get() {
  static const SecurityConfig cfg = [] {
    SecurityConfig c;
    c.enabled    = EnvBool("UPF_SEC_ENABLED", c.enabled);
    c.port       = (uint16_t) EnvU64("UPF_SEC_PORT", c.port);
    c.db_path    = EnvStr("UPF_SEC_DB_PATH", c.db_path);
    c.audit_path = EnvStr("UPF_SEC_AUDIT_PATH", c.audit_path);
    c.max_ttl_s  = (uint32_t) EnvU64("UPF_SEC_MAX_TTL_S", c.max_ttl_s);
    c.max_cmds_per_s =
        (uint32_t) EnvU64("UPF_SEC_MAX_CMDS_PER_S", c.max_cmds_per_s);
    c.max_blocked_ratio =
        EnvDouble("UPF_SEC_MAX_BLOCKED_RATIO", c.max_blocked_ratio);
    c.max_policies = (uint32_t) EnvU64("UPF_SEC_MAX_POLICIES", c.max_policies);
    if (c.max_policies == 0) c.max_policies = 1;
    c.ratelimit_burst_ms =
        (uint32_t) EnvU64("UPF_SEC_RATELIMIT_BURST_MS", c.ratelimit_burst_ms);
    c.sweep_s = (uint32_t) EnvU64("UPF_SEC_SWEEP_S", c.sweep_s);
    if (c.sweep_s == 0) c.sweep_s = 1;
    c.profile        = EnvBool("UPF_SEC_PROFILE", c.profile);
    c.drop_spoofed    = EnvBool("UPF_SEC_DROP_SPOOFED", c.drop_spoofed);
    c.drop_gtp_in_gtp = EnvBool("UPF_SEC_DROP_GTP_IN_GTP", c.drop_gtp_in_gtp);
    c.drop_unknown_ul = EnvBool("UPF_SEC_DROP_UNKNOWN_UL", c.drop_unknown_ul);
    c.reflex_mode     = EnvStr("UPF_SEC_REFLEX_MODE", c.reflex_mode);
    c.reflex_quota_ul_bytes = EnvU64("UPF_SEC_REFLEX_QUOTA_UL_BYTES", c.reflex_quota_ul_bytes);
    c.reflex_rate_ul_kbps   = EnvU64("UPF_SEC_REFLEX_RATE_UL_KBPS", c.reflex_rate_ul_kbps);
    c.reflex_ttl_s     = (uint32_t) EnvU64("UPF_SEC_REFLEX_TTL_S", c.reflex_ttl_s);
    if (c.reflex_ttl_s == 0) c.reflex_ttl_s = 1;
    c.reflex_ttl_max_s = (uint32_t) EnvU64("UPF_SEC_REFLEX_TTL_MAX_S", c.reflex_ttl_max_s);
    if (c.reflex_ttl_max_s < c.reflex_ttl_s) c.reflex_ttl_max_s = c.reflex_ttl_s;
    c.reflex_max_share = EnvDouble("UPF_SEC_REFLEX_MAX_SHARE", c.reflex_max_share);
    c.telemetry_ring = (uint32_t) EnvU64("UPF_SEC_TELEMETRY_RING", c.telemetry_ring);
    if (c.telemetry_ring == 0) c.telemetry_ring = 1;
    return c;
  }();
  return cfg;
}

//------------------------------------------------------------------------------
SecurityPolicyStore& SecurityPolicyStore::GetInstance() {
  static SecurityPolicyStore inst;
  return inst;
}

SecurityPolicyStore::~SecurityPolicyStore() {
  Stop();
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::Start(
    std::shared_ptr<BPFMap> by_supi, std::shared_ptr<BPFMap> by_seid,
    std::shared_ptr<BPFMap> stats) {
  std::unique_lock<std::mutex> lk(mtx_);
  if (running_) return true;
  if (!by_supi || !by_seid || !stats) {
    Logger::upf_app().error("UPF security: sec_policy maps not found");
    return false;
  }
  by_supi_    = by_supi;
  by_seid_    = by_seid;
  stats_      = stats;
  fd_by_supi_ = by_supi_->GetFd();
  fd_by_seid_ = by_seid_->GetFd();
  fd_stats_   = stats_->GetFd();
  ncpus_      = std::max(1, libbpf_num_possible_cpus());

  std::ifstream bid("/proc/sys/kernel/random/uuid");
  std::getline(bid, boot_id_);
  started_at_ms_ = WallMs();

  if (!OpenDb()) return false;

  // Reload the subscriber memory; expired rows are dropped here
  const int64_t now = WallMs();
  sqlite3_stmt* st  = nullptr;
  sqlite3_prepare_v2(
      db_,
      "SELECT supi, action, rate_ul_kbps, rate_dl_kbps, expires_at_ms, epoch, "
      "level, updated_at_ms FROM policy",
      -1, &st, nullptr);
  std::vector<std::string> expired;
  while (st && sqlite3_step(st) == SQLITE_ROW) {
    SecPolicyRecord r;
    r.supi          = (const char*) sqlite3_column_text(st, 0);
    r.action        = (const char*) sqlite3_column_text(st, 1);
    r.rate_ul_kbps  = sqlite3_column_int64(st, 2);
    r.rate_dl_kbps  = sqlite3_column_int64(st, 3);
    r.expires_at_ms = sqlite3_column_int64(st, 4);
    r.epoch         = sqlite3_column_int64(st, 5);
    r.level         = sqlite3_column_int(st, 6);
    r.updated_at_ms = sqlite3_column_int64(st, 7);
    if (!ActiveLocked(r, now)) {
      expired.push_back(r.supi);
      continue;
    }
    policies_[r.supi] = r;
    ApplyLocked(r);
  }
  sqlite3_finalize(st);
  for (const auto& s : expired) DbDelete(s);

  Logger::upf_app().info(
      "UPF security: %zu policies loaded from %s (%zu expired dropped), "
      "boot_id %s",
      policies_.size(), SecurityConfig::Get().db_path.c_str(), expired.size(),
      boot_id_.c_str());
  Audit("load", "", 200, {{"policies", policies_.size()}}, "local");

  running_ = true;
  sweeper_ = std::thread(&SecurityPolicyStore::SweepLoop, this);
  return true;
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::Stop() {
  {
    std::lock_guard<std::mutex> lk(mtx_);
    if (!running_) return;
    running_ = false;
  }
  sweep_cv_.notify_all();
  if (sweeper_.joinable()) sweeper_.join();
  tel_running_ = false;
  if (telemetry_.joinable()) telemetry_.join();
  std::lock_guard<std::mutex> lk(mtx_);
  if (db_) sqlite3_close(db_);
  db_ = nullptr;
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::OpenDb() {
  const auto& cfg = SecurityConfig::Get();
  MkdirParent(cfg.db_path);
  MkdirParent(cfg.audit_path);
  if (sqlite3_open_v2(
          cfg.db_path.c_str(), &db_,
          SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX,
          nullptr) != SQLITE_OK) {
    Logger::upf_app().error(
        "UPF security: cannot open %s: %s", cfg.db_path.c_str(),
        db_ ? sqlite3_errmsg(db_) : "?");
    return false;
  }
  char* err       = nullptr;
  const char* ddl =
      "CREATE TABLE IF NOT EXISTS policy("
      " supi TEXT PRIMARY KEY, action TEXT NOT NULL,"
      " rate_ul_kbps INTEGER, rate_dl_kbps INTEGER, expires_at_ms INTEGER,"
      " epoch INTEGER, level INTEGER, updated_at_ms INTEGER);"
      "CREATE TABLE IF NOT EXISTS audit("
      " id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER, op TEXT,"
      " supi TEXT, status INTEGER, detail TEXT, peer TEXT);";
  if (sqlite3_exec(db_, ddl, nullptr, nullptr, &err) != SQLITE_OK) {
    Logger::upf_app().error("UPF security: schema: %s", err ? err : "?");
    sqlite3_free(err);
    return false;
  }
  return true;
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::DbUpsert(const SecPolicyRecord& r) {
  sqlite3_stmt* st = nullptr;
  if (sqlite3_prepare_v2(
          db_,
          "INSERT OR REPLACE INTO policy(supi, action, rate_ul_kbps, "
          "rate_dl_kbps, expires_at_ms, epoch, level, updated_at_ms) "
          "VALUES(?,?,?,?,?,?,?,?)",
          -1, &st, nullptr) != SQLITE_OK)
    return false;
  sqlite3_bind_text(st, 1, r.supi.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(st, 2, r.action.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_int64(st, 3, r.rate_ul_kbps);
  sqlite3_bind_int64(st, 4, r.rate_dl_kbps);
  sqlite3_bind_int64(st, 5, r.expires_at_ms);
  sqlite3_bind_int64(st, 6, r.epoch);
  sqlite3_bind_int(st, 7, r.level);
  sqlite3_bind_int64(st, 8, r.updated_at_ms);
  bool ok = sqlite3_step(st) == SQLITE_DONE;
  sqlite3_finalize(st);
  return ok;
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::DbDelete(const std::string& supi) {
  sqlite3_stmt* st = nullptr;
  if (sqlite3_prepare_v2(
          db_, "DELETE FROM policy WHERE supi = ?", -1, &st, nullptr) !=
      SQLITE_OK)
    return false;
  sqlite3_bind_text(st, 1, supi.c_str(), -1, SQLITE_TRANSIENT);
  bool ok = sqlite3_step(st) == SQLITE_DONE;
  sqlite3_finalize(st);
  return ok;
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::Audit(
    const std::string& op, const std::string& supi, int status,
    const json& detail, const std::string& peer) {
  const int64_t ts = WallMs();
  json line = {{"ts_ms", ts},       {"op", op},     {"supi", supi},
               {"status", status},  {"detail", detail}, {"peer", peer}};
  std::ofstream f(SecurityConfig::Get().audit_path, std::ios::app);
  if (f) f << line.dump() << "\n";
  if (!db_) return;
  sqlite3_stmt* st = nullptr;
  if (sqlite3_prepare_v2(
          db_,
          "INSERT INTO audit(ts_ms, op, supi, status, detail, peer) "
          "VALUES(?,?,?,?,?,?)",
          -1, &st, nullptr) != SQLITE_OK)
    return;
  const std::string d = detail.dump();
  sqlite3_bind_int64(st, 1, ts);
  sqlite3_bind_text(st, 2, op.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(st, 3, supi.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_int(st, 4, status);
  sqlite3_bind_text(st, 5, d.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_bind_text(st, 6, peer.c_str(), -1, SQLITE_TRANSIENT);
  sqlite3_step(st);
  sqlite3_finalize(st);
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::ActiveLocked(
    const SecPolicyRecord& r, int64_t now_ms) const {
  return r.expires_at_ms == 0 || r.expires_at_ms > now_ms;
}

//------------------------------------------------------------------------------
struct sec_policy SecurityPolicyStore::ToKernel(const SecPolicyRecord& r) const {
  struct sec_policy p = {};
  p.action            = ActionCode(r.action);
  p.level             = r.level;
  p.rate_ul_bytes_s   = r.rate_ul_kbps * 1000 / 8;
  p.rate_dl_bytes_s   = r.rate_dl_kbps * 1000 / 8;
  // Bucket depth: burst_ms of traffic, at least two full-size packets
  const uint64_t ms = SecurityConfig::Get().ratelimit_burst_ms;
  p.burst_ul_bytes  = std::max<uint64_t>(p.rate_ul_bytes_s * ms / 1000, 3000);
  p.burst_dl_bytes  = std::max<uint64_t>(p.rate_dl_bytes_s * ms / 1000, 3000);
  p.tokens_ul       = p.burst_ul_bytes;
  p.tokens_dl       = p.burst_dl_bytes;
  if (r.expires_at_ms) {
    const int64_t left_ms = std::max<int64_t>(r.expires_at_ms - WallMs(), 0);
    p.expires_at_ns       = MonoNs() + (uint64_t) left_ms * 1000000ULL;
    if (p.expires_at_ns == 0) p.expires_at_ns = 1;
  }
  p.epoch = r.epoch;
  return p;
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::WriteSeidLocked(
    uint64_t seid, const struct sec_policy& p) {
  if (bpf_map_update_elem(fd_by_seid_, &seid, &p, BPF_ANY) != 0)
    Logger::upf_app().error(
        "UPF security: sec_policy_by_seid update failed for SEID " SEID_FMT
        " (errno %d)",
        seid, errno);
  // Counters keep their values across policy changes of a session
  std::vector<struct sec_stats> zero(ncpus_);
  bpf_map_update_elem(fd_stats_, &seid, zero.data(), BPF_NOEXIST);
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::ApplyLocked(const SecPolicyRecord& r) {
  uint64_t imsi = 0;
  if (!ParseSupi(r.supi, imsi)) return;
  const struct sec_policy p = ToKernel(r);
  if (bpf_map_update_elem(fd_by_supi_, &imsi, &p, BPF_ANY) != 0)
    Logger::upf_app().error(
        "UPF security: sec_policy_by_supi update failed for %s (errno %d)",
        r.supi.c_str(), errno);
  for (const auto& [seid, supi] : seid_supi_)
    if (supi == r.supi) WriteSeidLocked(seid, p);
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::ClearLocked(const std::string& supi) {
  uint64_t imsi = 0;
  if (ParseSupi(supi, imsi)) bpf_map_delete_elem(fd_by_supi_, &imsi);
  for (const auto& [seid, s] : seid_supi_)
    if (s == supi) bpf_map_delete_elem(fd_by_seid_, &seid);
}

//------------------------------------------------------------------------------
bool SecurityPolicyStore::ReadStatsLocked(
    uint64_t seid, struct sec_stats& sum) const {
  std::vector<struct sec_stats> v(ncpus_);
  if (bpf_map_lookup_elem(fd_stats_, &seid, v.data()) != 0) return false;
  for (const auto& s : v) AddStats(sum, s);
  return true;
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::OnSessionEstablished(
    uint64_t seid, const std::string& supi) {
  if (!running_ || supi.empty()) return;
  std::lock_guard<std::mutex> lk(mtx_);
  seid_supi_[seid] = supi;
  auto it          = policies_.find(supi);
  if (it == policies_.end() || !ActiveLocked(it->second, WallMs())) return;
  // Written before the session pipeline (session_by_ue_ip_map) exists, so
  // the first packet of the session already sees the policy
  WriteSeidLocked(seid, ToKernel(it->second));
  Logger::upf_app().info(
      "UPF security: %s policy applied to new session SEID " SEID_FMT,
      it->second.action.c_str(), seid);
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::OnSessionRemoved(uint64_t seid) {
  if (!running_) return;
  std::lock_guard<std::mutex> lk(mtx_);
  auto it = seid_supi_.find(seid);
  if (it != seid_supi_.end()) {
    struct sec_stats s = {};
    if (ReadStatsLocked(seid, s)) AddStats(closed_stats_[it->second], s);
    seid_supi_.erase(it);
  }
  bpf_map_delete_elem(fd_by_seid_, &seid);
  bpf_map_delete_elem(fd_stats_, &seid);
  if (fd_profile_ >= 0) bpf_map_delete_elem(fd_profile_, &seid);
  if (fd_dst_bits_ >= 0) bpf_map_delete_elem(fd_dst_bits_, &seid);
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::RecordJsonLocked(const SecPolicyRecord& r) const {
  json seids = json::array();
  bool enforced = false;
  for (const auto& [seid, s] : seid_supi_) {
    if (s != r.supi) continue;
    struct sec_policy p;
    uint64_t k = seid;
    bool in_map = bpf_map_lookup_elem(fd_by_seid_, &k, &p) == 0;
    enforced |= in_map;
    seids.push_back({{"seid", seid}, {"in_map", in_map}});
  }
  const int64_t now = WallMs();
  return {{"supi", r.supi},
          {"action", r.action},
          {"rate_ul_kbps", r.rate_ul_kbps},
          {"rate_dl_kbps", r.rate_dl_kbps},
          {"expires_at_ms", r.expires_at_ms},
          {"expires_in_s",
           r.expires_at_ms ? std::max<int64_t>(r.expires_at_ms - now, 0) / 1000.0
                           : -1.0},
          {"epoch", r.epoch},
          {"level", r.level},
          {"updated_at_ms", r.updated_at_ms},
          {"active", ActiveLocked(r, now)},
          {"sessions", seids},
          {"enforced", enforced}};
}

//------------------------------------------------------------------------------
SecurityPolicyStore::Reply SecurityPolicyStore::Put(
    const std::string& supi, const std::string& body, const std::string& peer) {
  const auto& cfg = SecurityConfig::Get();
  std::lock_guard<std::mutex> lk(mtx_);
  if (!running_) return {503, {{"error", "security store not running"}}};

  const int64_t now = WallMs();
  auto reject       = [&](int status, const std::string& why,
                    json detail = json::object()) -> Reply {
    detail["reason"] = why;
    Audit("put", supi, status, detail, peer);
    return {status, {{"error", why}}};
  };

  // Command rate (sliding 1 s window over accepted-for-processing commands)
  while (!cmd_times_ms_.empty() && now - cmd_times_ms_.front() >= 1000)
    cmd_times_ms_.pop_front();
  if (cmd_times_ms_.size() >= cfg.max_cmds_per_s)
    return reject(429, "command rate limit exceeded");
  cmd_times_ms_.push_back(now);

  uint64_t imsi = 0;
  if (!ParseSupi(supi, imsi)) return reject(400, "invalid SUPI");

  json req = json::parse(body, nullptr, false);
  if (req.is_discarded() || !req.is_object())
    return reject(400, "body is not a JSON object");

  SecPolicyRecord r;
  r.supi   = supi;
  r.action = req.value("action", "");
  if (ActionCode(r.action) == SEC_ACTION_NONE)
    return reject(400, "action must be block, ratelimit or monitor", req);
  if (!req.contains("ttl_s") || !req["ttl_s"].is_number_unsigned() ||
      req["ttl_s"].get<uint64_t>() == 0)
    return reject(400, "ttl_s must be a positive integer", req);
  const uint64_t ttl_s = req["ttl_s"].get<uint64_t>();
  if (ttl_s > cfg.max_ttl_s) return reject(403, "ttl_s above maxTtlS", req);
  r.rate_ul_kbps = req.value("rate_ul_kbps", (uint64_t) 0);
  r.rate_dl_kbps = req.value("rate_dl_kbps", (uint64_t) 0);
  if (r.action == "ratelimit" && !r.rate_ul_kbps && !r.rate_dl_kbps)
    return reject(400, "ratelimit needs rate_ul_kbps or rate_dl_kbps", req);
  r.level         = req.value("level", (uint32_t) 0);
  r.expires_at_ms = now + (int64_t) ttl_s * 1000;
  r.updated_at_ms = now;

  auto old = policies_.find(supi);
  if (req.contains("epoch")) {
    r.epoch = req.value("epoch", (uint64_t) 0);
    if (old != policies_.end() && r.epoch < old->second.epoch)
      return reject(409, "stale epoch", req);
  } else {
    r.epoch = (old != policies_.end()) ? old->second.epoch + 1 : 1;
  }

  // At most max_blocked_ratio of the known subscribers blocked at once.
  // Known = live sessions' SUPIs plus every SUPI with an active block.
  if (r.action == "block") {
    std::set<std::string> known, blocked;
    for (const auto& [seid, s] : seid_supi_) known.insert(s);
    for (const auto& [s, p] : policies_)
      if (p.action == "block" && ActiveLocked(p, now)) blocked.insert(s);
    blocked.insert(supi);
    known.insert(blocked.begin(), blocked.end());
    const double ratio = (double) blocked.size() / (double) known.size();
    if (ratio > cfg.max_blocked_ratio + 1e-9)
      return reject(
          403, "blocked ratio above maxBlockedRatio",
          {{"blocked", blocked.size()}, {"known", known.size()}});
  }

  if (old == policies_.end() && policies_.size() >= cfg.max_policies)
    return reject(507, "policy table full");

  // DB first: a policy the API acknowledged survives a UPF restart
  if (!DbUpsert(r)) return reject(500, "database write failed");
  policies_[supi] = r;
  ApplyLocked(r);

  json out = RecordJsonLocked(r);
  Audit("put", supi, 200, req, peer);
  Logger::upf_app().info(
      "UPF security: PUT %s %s ttl %" PRIu64 " s epoch %" PRIu64
      " (%zu live sessions)",
      supi.c_str(), r.action.c_str(), ttl_s, r.epoch, out["sessions"].size());
  return {200, out};
}

//------------------------------------------------------------------------------
SecurityPolicyStore::Reply SecurityPolicyStore::Delete(
    const std::string& supi, const std::string& peer) {
  const auto& cfg = SecurityConfig::Get();
  std::lock_guard<std::mutex> lk(mtx_);
  if (!running_) return {503, {{"error", "security store not running"}}};
  const int64_t now = WallMs();
  while (!cmd_times_ms_.empty() && now - cmd_times_ms_.front() >= 1000)
    cmd_times_ms_.pop_front();
  if (cmd_times_ms_.size() >= cfg.max_cmds_per_s) {
    Audit("delete", supi, 429, {{"reason", "command rate limit exceeded"}}, peer);
    return {429, {{"error", "command rate limit exceeded"}}};
  }
  cmd_times_ms_.push_back(now);

  auto it = policies_.find(supi);
  if (it == policies_.end()) {
    Audit("delete", supi, 404, json::object(), peer);
    return {404, {{"error", "no policy for SUPI"}}};
  }
  if (!DbDelete(supi)) {
    Audit("delete", supi, 500, {{"reason", "database write failed"}}, peer);
    return {500, {{"error", "database write failed"}}};
  }
  ClearLocked(supi);
  policies_.erase(it);
  Audit("delete", supi, 200, json::object(), peer);
  Logger::upf_app().info("UPF security: DELETE %s", supi.c_str());
  return {200, {{"supi", supi}, {"deleted", true}}};
}

//------------------------------------------------------------------------------
SecurityPolicyStore::Reply SecurityPolicyStore::Get(const std::string& supi) {
  std::lock_guard<std::mutex> lk(mtx_);
  auto it = policies_.find(supi);
  if (it == policies_.end()) return {404, {{"error", "no policy for SUPI"}}};
  return {200, RecordJsonLocked(it->second)};
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::List() {
  std::lock_guard<std::mutex> lk(mtx_);
  json arr = json::array();
  for (const auto& [s, r] : policies_) arr.push_back(RecordJsonLocked(r));
  return {{"policies", arr}, {"count", arr.size()}};
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::Stats(const std::string& supi) {
  std::lock_guard<std::mutex> lk(mtx_);
  std::map<std::string, struct sec_stats> live;
  std::map<std::string, json> seids;
  for (const auto& [seid, s] : seid_supi_) {
    if (!supi.empty() && s != supi) continue;
    struct sec_stats st = {};
    ReadStatsLocked(seid, st);
    AddStats(live[s], st);
    seids[s].push_back({{"seid", seid}, {"stats", StatsJson(st)}});
  }
  std::set<std::string> keys;
  for (const auto& [s, v] : live) keys.insert(s);
  for (const auto& [s, v] : closed_stats_)
    if (supi.empty() || s == supi) keys.insert(s);
  if (!supi.empty()) keys.insert(supi);

  json arr = json::array();
  for (const auto& s : keys) {
    struct sec_stats total = {};
    if (live.count(s)) AddStats(total, live[s]);
    if (closed_stats_.count(s)) AddStats(total, closed_stats_[s]);
    arr.push_back(
        {{"supi", s},
         {"total", StatsJson(total)},
         {"sessions", seids.count(s) ? seids[s] : json::array()}});
  }
  return {{"stats", arr}};
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::Sessions() {
  std::lock_guard<std::mutex> lk(mtx_);
  json arr = json::array();
  for (const auto& [seid, s] : seid_supi_) {
    struct sec_policy p;
    uint64_t k  = seid;
    bool in_map = bpf_map_lookup_elem(fd_by_seid_, &k, &p) == 0;
    arr.push_back({{"seid", seid}, {"supi", s}, {"policy_in_map", in_map}});
  }
  return {{"sessions", arr}};
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::Info() {
  const auto& cfg = SecurityConfig::Get();
  std::lock_guard<std::mutex> lk(mtx_);
  return {{"service", "oai-upf-security"},
          {"version", "C35"},
          {"running", running_.load()},
          {"boot_id", boot_id_},
          {"started_at_ms", started_at_ms_},
          {"policies", policies_.size()},
          {"live_sessions", seid_supi_.size()},
          {"limits",
           {{"maxTtlS", cfg.max_ttl_s},
            {"maxCmdsPerS", cfg.max_cmds_per_s},
            {"maxBlockedRatio", cfg.max_blocked_ratio},
            {"maxPolicies", cfg.max_policies},
            {"ratelimitBurstMs", cfg.ratelimit_burst_ms}}},
          {"db_path", cfg.db_path},
          {"profile", tel_running_.load()},
          {"fixed_rules",
           {{"dropSpoofed", cfg.drop_spoofed},
            {"dropGtpInGtp", cfg.drop_gtp_in_gtp},
            {"dropUnknownUl", cfg.drop_unknown_ul}}},
          {"unknown_ul_drop", UnknownUlDropsLocked()},
          {"reflex",
           {{"mode", cfg.reflex_mode},
            {"quotaUlBytes", cfg.reflex_quota_ul_bytes},
            {"rateUlKbps", cfg.reflex_rate_ul_kbps},
            {"ttlS", cfg.reflex_ttl_s},
            {"ttlMaxS", cfg.reflex_ttl_max_s},
            {"maxShare", cfg.reflex_max_share}}},
          {"telemetry_epoch", tel_epoch_}};
}

//------------------------------------------------------------------------------
namespace {

void AddProfile(struct sec_profile& a, const struct sec_profile& b) {
  const uint64_t* x = reinterpret_cast<const uint64_t*>(&b);
  uint64_t* y       = reinterpret_cast<uint64_t*>(&a);
  for (size_t i = 0; i < sizeof(a) / sizeof(uint64_t); i++) y[i] += x[i];
}

// Counter differences of one window (a counter that went back = new entry)
json ProfileJson(const struct sec_profile& now, const struct sec_profile& prev) {
  auto d = [](uint64_t n, uint64_t p) { return n >= p ? n - p : n; };
  return {{"ul_pkts", d(now.ul_pkts, prev.ul_pkts)},
          {"ul_bytes", d(now.ul_bytes, prev.ul_bytes)},
          {"dl_pkts", d(now.dl_pkts, prev.dl_pkts)},
          {"dl_bytes", d(now.dl_bytes, prev.dl_bytes)},
          {"ul_tcp", d(now.ul_tcp, prev.ul_tcp)},
          {"ul_tcp_syn", d(now.ul_tcp_syn, prev.ul_tcp_syn)},
          {"ul_udp", d(now.ul_udp, prev.ul_udp)},
          {"ul_icmp", d(now.ul_icmp, prev.ul_icmp)},
          {"ul_frag", d(now.ul_frag, prev.ul_frag)},
          {"ul_dns", d(now.ul_dns, prev.ul_dns)},
          {"ul_gtp_in_gtp", d(now.ul_gtp_in_gtp, prev.ul_gtp_in_gtp)},
          {"dl_tcp", d(now.dl_tcp, prev.dl_tcp)},
          {"dl_tcp_syn", d(now.dl_tcp_syn, prev.dl_tcp_syn)},
          {"dl_udp", d(now.dl_udp, prev.dl_udp)},
          {"dl_icmp", d(now.dl_icmp, prev.dl_icmp)},
          {"dl_frag", d(now.dl_frag, prev.dl_frag)},
          {"ul_spoof_drop", d(now.ul_spoof_drop, prev.ul_spoof_drop)},
          {"ul_gtp_in_gtp_drop", d(now.ul_gtp_in_gtp_drop, prev.ul_gtp_in_gtp_drop)}};
}

// Linear counting over a 64-bit bitmap: n = -m ln(z/m), m = 64 (saturates
// near 260 destinations; 0 bits free -> reported as 64 * ln 64)
double DistinctEstimate(uint64_t bits) {
  const int set = __builtin_popcountll(bits);
  const double m = 64, z = std::max(1, 64 - set);
  return set == 0 ? 0.0 : -m * std::log(z / m);
}

}  // namespace

//------------------------------------------------------------------------------
bool SecurityPolicyStore::StartTelemetry(
    std::shared_ptr<BPFMap> profile, std::shared_ptr<BPFMap> dst_bits,
    std::shared_ptr<BPFMap> config, std::shared_ptr<BPFMap> global) {
  const auto& cfg = SecurityConfig::Get();
  if (global) {
    global_    = global;
    fd_global_ = global_->GetFd();
  }
  if (!profile || !dst_bits || !config) {
    Logger::upf_app().error("UPF security: sec_profile maps not found");
    return false;
  }
  // The fixed rules are written even with the telemetry off
  uint32_t key        = 0;
  struct sec_config c = {};
  c.profile_enabled   = cfg.profile;
  c.drop_spoofed      = cfg.drop_spoofed;
  c.drop_gtp_in_gtp   = cfg.drop_gtp_in_gtp;
  c.drop_unknown_ul   = cfg.drop_unknown_ul;
  if (bpf_map_update_elem(config->GetFd(), &key, &c, BPF_ANY) != 0) {
    Logger::upf_app().error("UPF security: sec_config update failed (errno %d)", errno);
    return false;
  }
  {
    std::lock_guard<std::mutex> tl(tel_mtx_);
    rx_mode_           = cfg.reflex_mode;
    rx_quota_ul_bytes_ = cfg.reflex_quota_ul_bytes;
    rx_rate_ul_kbps_   = cfg.reflex_rate_ul_kbps;
    rx_ttl_s_          = cfg.reflex_ttl_s;
    rx_ttl_max_s_      = cfg.reflex_ttl_max_s;
    rx_max_share_      = cfg.reflex_max_share;
  }
  Logger::upf_app().info(
      "UPF security: fixed rules: drop spoofed %d, GTP-in-GTP %d, unknown UL source %d",
      cfg.drop_spoofed, cfg.drop_gtp_in_gtp, cfg.drop_unknown_ul);
  if (!cfg.profile) {
    Logger::upf_app().info("UPF security: packet-mix telemetry off (UPF_SEC_PROFILE)");
    return true;
  }
  profile_     = profile;
  dst_bits_    = dst_bits;
  config_      = config;
  fd_profile_  = profile_->GetFd();
  fd_dst_bits_ = dst_bits_->GetFd();
  char epoch[32];
  const time_t t = time(nullptr);
  struct tm tm;
  gmtime_r(&t, &tm);
  strftime(epoch, sizeof(epoch), "%Y%m%dT%H%M%SZ", &tm);
  tel_epoch_   = epoch;
  tel_running_ = true;
  telemetry_   = std::thread(&SecurityPolicyStore::TelemetryLoop, this);
  Logger::upf_app().info(
      "UPF security: packet-mix telemetry on, source_epoch %s, ring %u",
      tel_epoch_.c_str(), SecurityConfig::Get().telemetry_ring);
  return true;
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::UnknownUlDropsLocked() const {
  if (fd_global_ < 0) return nullptr;
  std::vector<struct sec_global> v(ncpus_);
  uint32_t key = 0;
  if (bpf_map_lookup_elem(fd_global_, &key, v.data()) != 0) return nullptr;
  uint64_t pkts = 0, bytes = 0;
  for (const auto& g : v) {
    pkts += g.unknown_ul_drop_pkts;
    bytes += g.unknown_ul_drop_bytes;
  }
  return {{"pkts", pkts}, {"bytes", bytes}};
}

//------------------------------------------------------------------------------
// One tick just after each wall-clock second: the window [end-1, end) like
// the PFCP End Time of URR, so the xApp joins both on the same second
void SecurityPolicyStore::TelemetryLoop() {
  using namespace std::chrono;
  while (tel_running_ && running_) {
    const auto now  = system_clock::now();
    const auto next = time_point_cast<seconds>(now) + seconds(1);
    std::this_thread::sleep_until(next + milliseconds(20));
    TelemetryTick(duration_cast<seconds>(next.time_since_epoch()).count());
  }
}

void SecurityPolicyStore::TelemetryTick(int64_t end_unix) {
  std::vector<std::pair<uint64_t, std::string>> live;
  {
    std::lock_guard<std::mutex> lk(mtx_);
    live.assign(seid_supi_.begin(), seid_supi_.end());
  }
  const int n = ncpus_;
  std::vector<struct sec_profile> per_cpu(n);
  std::vector<uint64_t> bits(n), zero_bits(n, 0);
  std::lock_guard<std::mutex> tl(tel_mtx_);
  std::unordered_map<uint64_t, struct sec_profile> seen;
  struct UlWindow { std::string supi; uint64_t seid, ul_bytes; };
  std::vector<UlWindow> ul_windows;
  for (const auto& [seid, supi] : live) {
    uint64_t k           = seid;
    struct sec_profile s = {};
    if (bpf_map_lookup_elem(fd_profile_, &k, per_cpu.data()) == 0)
      for (const auto& x : per_cpu) AddProfile(s, x);
    uint64_t or_bits = 0;
    if (bpf_map_lookup_elem(fd_dst_bits_, &k, bits.data()) == 0) {
      for (auto b : bits) or_bits |= b;
      bpf_map_update_elem(fd_dst_bits_, &k, zero_bits.data(), BPF_EXIST);
    }
    const struct sec_profile prev = tel_last_.count(seid) ? tel_last_[seid] : sec_profile{};
    seen[seid]                    = s;
    json body                     = ProfileJson(s, prev);
    body["ul_dst_estimate"]       = DistinctEstimate(or_bits);
    ul_windows.push_back({supi, seid, body["ul_bytes"].get<uint64_t>()});
    tel_ring_.push_back(
        {{"seq", ++tel_seq_},
         {"supi", supi},
         {"seid", seid},
         {"time_unix", end_unix},
         {"window_ms", 1000},
         {"body", body}});
  }
  // reflex decisions and expiry: one mtx_ section (tel_mtx_ held -> mtx_;
  // this order is used nowhere in reverse, so no deadlock)
  {
    std::lock_guard<std::mutex> lk(mtx_);
    const int64_t now = WallMs();
    for (const auto& w : ul_windows)
      EvaluateReflexLocked(w.supi, w.seid, w.ul_bytes, end_unix, now);
    ExpireReflexesLocked(now);
  }
  tel_last_.swap(seen);  // ended sessions drop out
  while (tel_ring_.size() > SecurityConfig::Get().telemetry_ring) tel_ring_.pop_front();
}

json SecurityPolicyStore::Telemetry(uint64_t since, size_t limit) {
  std::lock_guard<std::mutex> tl(tel_mtx_);
  json out     = json::array();
  bool gap     = !tel_ring_.empty() && tel_ring_.front()["seq"].get<uint64_t>() > since + 1;
  for (const auto& r : tel_ring_) {
    if (r["seq"].get<uint64_t>() <= since) continue;
    if (out.size() >= limit) break;
    out.push_back(r);
  }
  return {{"source", "upf"},
          {"source_epoch", tel_epoch_},
          {"enabled", tel_running_.load()},
          {"last_seq", tel_seq_},
          {"gap", gap},
          {"records", out}};
}

//------------------------------------------------------------------------------
// reflexes_ and event_ring_ are guarded by tel_mtx_ (held by the caller);
// policies_, seid_supi_ and the BPF maps by mtx_ (locked by the caller).
void SecurityPolicyStore::PushEventLocked(const json& ev) {
  json e = ev;
  e["seq"] = ++event_seq_;
  event_ring_.push_back(e);
  while (event_ring_.size() > SecurityConfig::Get().telemetry_ring)
    event_ring_.pop_front();
}

void SecurityPolicyStore::EvaluateReflexLocked(
    const std::string& supi, uint64_t seid, uint64_t ul_bytes_window,
    int64_t end_unix, int64_t now) {
  // runtime reflex parameters (xApp-set); guarded by tel_mtx_, held by caller
  const std::string mode = rx_mode_;
  const uint64_t quota = rx_quota_ul_bytes_, rate = rx_rate_ul_kbps_;
  const uint32_t ttl0 = rx_ttl_s_, ttl_max = rx_ttl_max_s_;
  const double max_share = rx_max_share_;
  const bool trip = ul_bytes_window > quota;

  // An active xApp policy owns this subscriber: it always wins, so the reflex
  // stands down (its kernel entry, if any, was already overwritten by the
  // xApp policy in ApplyLocked).
  auto pol = policies_.find(supi);
  const bool xapp_owns =
      pol != policies_.end() && ActiveLocked(pol->second, now) &&
      (pol->second.action == "ratelimit" || pol->second.action == "block");
  if (xapp_owns) {
    reflexes_.erase(supi);
    return;
  }
  if (!trip) return;

  // "off": detect and report only, never act (the switch the thesis compares)
  if (mode != "ratelimit") {
    PushEventLocked(
        {{"event", "trip"}, {"rule", "ul_volume_quota"}, {"action", "report"},
         {"supi", supi}, {"seid", seid}, {"time_unix", end_unix},
         {"ul_bytes", ul_bytes_window}, {"quota_ul_bytes", quota}});
    return;
  }

  // Bound the share of live sessions under a reflex at once
  auto it = reflexes_.find(supi);
  if (it == reflexes_.end()) {
    const size_t live = std::max<size_t>(seid_supi_.size(), 1);
    if ((double) (reflexes_.size() + 1) / (double) live > max_share + 1e-9) {
      PushEventLocked(
          {{"event", "trip"}, {"rule", "ul_volume_quota"}, {"action", "suppressed_max_share"},
           {"supi", supi}, {"seid", seid}, {"time_unix", end_unix},
           {"ul_bytes", ul_bytes_window}});
      return;
    }
  }

  // Install or renew: ratelimit UL only (rate_dl 0 = DL untouched), short TTL.
  // A repeat within the current TTL doubles it, up to reflex_ttl_max_s.
  uint32_t ttl = ttl0;
  if (it != reflexes_.end() && now - it->second.last_trip_ms <= (int64_t) it->second.ttl_s * 1000)
    ttl = std::min(it->second.ttl_s * 2, ttl_max);
  Reflex rx{seid, now + (int64_t) ttl * 1000, ttl, now};
  reflexes_[supi] = rx;

  SecPolicyRecord r;
  r.supi          = supi;
  r.action        = "ratelimit";
  r.rate_ul_kbps  = rate;
  r.rate_dl_kbps  = 0;  // uplink only (the thesis decision of 18/10)
  r.expires_at_ms = rx.expires_at_ms;
  WriteSeidLocked(seid, ToKernel(r));

  PushEventLocked(
      {{"event", "reflex"}, {"rule", "ul_volume_quota"}, {"action", "ratelimit_ul"},
       {"supi", supi}, {"seid", seid}, {"time_unix", end_unix},
       {"ul_bytes", ul_bytes_window}, {"quota_ul_bytes", quota},
       {"rate_ul_kbps", rate}, {"ttl_s", ttl}});
  Logger::upf_app().info(
      "UPF security: reflex ratelimit UL %s SEID %" PRIu64 " (%" PRIu64
      " > %" PRIu64 " B/s), ttl %u s",
      supi.c_str(), seid, ul_bytes_window, quota, ttl);
}

void SecurityPolicyStore::ExpireReflexesLocked(int64_t now) {
  for (auto it = reflexes_.begin(); it != reflexes_.end();) {
    if (it->second.expires_at_ms > now) {
      ++it;
      continue;
    }
    // Only remove the kernel entry if no xApp policy took the session over
    auto pol = policies_.find(it->first);
    const bool xapp_owns =
        pol != policies_.end() && ActiveLocked(pol->second, now) &&
        (pol->second.action == "ratelimit" || pol->second.action == "block");
    if (!xapp_owns) {
      uint64_t k = it->second.seid;
      bpf_map_delete_elem(fd_by_seid_, &k);
    }
    PushEventLocked(
        {{"event", "reflex_expired"}, {"rule", "ul_volume_quota"},
         {"supi", it->first}, {"seid", it->second.seid},
         {"time_unix", (int64_t) (WallMs() / 1000)}});
    it = reflexes_.erase(it);
  }
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::ReflexConfig() {
  std::lock_guard<std::mutex> tl(tel_mtx_);
  return {{"mode", rx_mode_}, {"quota_ul_bytes", rx_quota_ul_bytes_},
          {"rate_ul_kbps", rx_rate_ul_kbps_}, {"ttl_s", rx_ttl_s_},
          {"ttl_max_s", rx_ttl_max_s_}, {"max_share", rx_max_share_},
          {"active_reflexes", reflexes_.size()}};
}

// PUT /v1/config: the xApp (or the gate) sets the reflex rule parameters at
// runtime. Only fields present are changed; mode is "off" or "ratelimit".
SecurityPolicyStore::Reply SecurityPolicyStore::PutConfig(
    const std::string& body, const std::string& peer) {
  json req = json::parse(body, nullptr, false);
  if (req.is_discarded() || !req.is_object())
    return {400, {{"error", "body is not a JSON object"}}};
  {
    std::lock_guard<std::mutex> tl(tel_mtx_);
    if (req.contains("reflex_mode")) {
      const std::string m = req["reflex_mode"].get<std::string>();
      if (m != "off" && m != "ratelimit")
        return {400, {{"error", "reflex_mode must be off or ratelimit"}}};
      rx_mode_ = m;
    }
    if (req.contains("reflex_quota_ul_bytes")) rx_quota_ul_bytes_ = req["reflex_quota_ul_bytes"].get<uint64_t>();
    if (req.contains("reflex_rate_ul_kbps")) rx_rate_ul_kbps_ = req["reflex_rate_ul_kbps"].get<uint64_t>();
    if (req.contains("reflex_ttl_s")) rx_ttl_s_ = std::max<uint32_t>(1, req["reflex_ttl_s"].get<uint32_t>());
    if (req.contains("reflex_ttl_max_s")) rx_ttl_max_s_ = std::max(rx_ttl_s_, req["reflex_ttl_max_s"].get<uint32_t>());
    if (req.contains("reflex_max_share")) rx_max_share_ = req["reflex_max_share"].get<double>();
  }
  Audit("config", "", 200, req, peer);
  Logger::upf_app().info("UPF security: reflex config updated by %s", peer.c_str());
  return {200, ReflexConfig()};
}

//------------------------------------------------------------------------------
json SecurityPolicyStore::Events(uint64_t since, size_t limit) {
  std::lock_guard<std::mutex> tl(tel_mtx_);
  json out = json::array();
  bool gap = !event_ring_.empty() && event_ring_.front()["seq"].get<uint64_t>() > since + 1;
  for (const auto& e : event_ring_) {
    if (e["seq"].get<uint64_t>() <= since) continue;
    if (out.size() >= limit) break;
    out.push_back(e);
  }
  return {{"source", "upf"}, {"source_epoch", tel_epoch_}, {"enabled", tel_running_.load()},
          {"last_seq", event_seq_}, {"gap", gap}, {"records", out}};
}

//------------------------------------------------------------------------------
void SecurityPolicyStore::SweepLoop() {
  const auto period = std::chrono::seconds(SecurityConfig::Get().sweep_s);
  std::unique_lock<std::mutex> lk(mtx_);
  while (running_) {
    sweep_cv_.wait_for(lk, period, [this] { return !running_; });
    if (!running_) break;
    // XDP already ignores expired entries; this only frees them
    const int64_t now = WallMs();
    for (auto it = policies_.begin(); it != policies_.end();) {
      if (ActiveLocked(it->second, now)) {
        ++it;
        continue;
      }
      DbDelete(it->first);
      ClearLocked(it->first);
      Audit("expire", it->first, 200, {{"action", it->second.action}}, "local");
      Logger::upf_app().info(
          "UPF security: %s policy of %s expired", it->second.action.c_str(),
          it->first.c_str());
      it = policies_.erase(it);
    }
  }
}
