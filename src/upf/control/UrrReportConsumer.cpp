/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#include "UrrReportConsumer.h"

#include <bpf/libbpf.h>
#include <algorithm>
#include <cerrno>
#include <cinttypes>
#include <ctime>
#include <limits>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "SessionManager.h"
#include "logger.hpp"
#include "pfcp_session.hpp"
#include "upf_n4.hpp"
#include "urr_types.h"
#include "wrappers/BPFMap.hpp"

extern oai::upf::app::upf_n4* upf_n4_inst;

namespace {
constexpr uint64_t kNanosecondsPerSecond = 1000000000ULL;
constexpr uint64_t kNtpUnixEpochOffset   = 2208988800ULL;

uint32_t SaturatingSeconds(uint64_t nanoseconds) {
  const uint64_t seconds = nanoseconds / kNanosecondsPerSecond;
  return seconds > std::numeric_limits<uint32_t>::max() ?
             std::numeric_limits<uint32_t>::max() :
             static_cast<uint32_t>(seconds);
}

pfcp::usage_report_trigger_t ToPfcpTrigger(uint8_t trigger) {
  pfcp::usage_report_trigger_t result = {};
  result.volth                        = !!(trigger & URR_TRIGGER_VOLTH);
  result.volqu                        = !!(trigger & URR_TRIGGER_VOLQU);
  result.timth                        = !!(trigger & URR_TRIGGER_TIMTH);
  result.timqu                        = !!(trigger & URR_TRIGGER_TIMQU);
  result.perio                        = !!(trigger & URR_TRIGGER_PERIO);
  result.start                        = !!(trigger & URR_TRIGGER_START);
  result.stop                         = !!(trigger & URR_TRIGGER_STOPT);
  result.droth                        = !!(trigger & URR_TRIGGER_DROTH);
  return result;
}
}  // namespace

UrrReportConsumer::UrrReportConsumer(
    std::shared_ptr<BPFMap> ringbuf_map,
    std::shared_ptr<SessionManager> session_manager,
    std::shared_ptr<BPFMap> volume_map, std::shared_ptr<BPFMap> config_map)
    : ringbuf_map_(std::move(ringbuf_map)),
      session_manager_(std::move(session_manager)),
      volume_map_(std::move(volume_map)),
      config_map_(std::move(config_map)) {}

UrrReportConsumer::~UrrReportConsumer() {
  Stop();
}

void UrrReportConsumer::Start() {
  if (running_.load()) return;
  if (!ringbuf_map_ || !session_manager_) {
    throw std::runtime_error("URR consumer dependencies are not initialized");
  }

  const int map_fd = ringbuf_map_->GetFd();
  if (map_fd < 0) {
    throw std::runtime_error("URR report ring buffer is not loaded");
  }

  ring_buffer_ = ring_buffer__new(
      map_fd, UrrReportConsumer::OnRingbufEvent, this, nullptr);
  if (!ring_buffer_) {
    throw std::runtime_error(
        "Failed to create URR report ring buffer consumer");
  }

  running_.store(true);
  worker_ = std::thread(&UrrReportConsumer::PollLoop, this);
  Logger::upf_app().info("URR report ring buffer consumer started");
}

void UrrReportConsumer::Stop() {
  running_.store(false);
  if (worker_.joinable()) worker_.join();
  if (ring_buffer_) {
    ring_buffer__free(ring_buffer_);
    ring_buffer_ = nullptr;
  }
  report_sequences_.clear();
  activity_.clear();
  last_reported_.clear();
}

int UrrReportConsumer::OnRingbufEvent(
    void* context, void* data, size_t data_size) {
  if (!context || !data || data_size != sizeof(struct urr_report_event)) {
    Logger::upf_app().error(
        "Invalid URR ring buffer event size: %zu (expected %zu)", data_size,
        sizeof(struct urr_report_event));
    return 0;
  }
  return static_cast<UrrReportConsumer*>(context)->HandleEvent(
      *static_cast<const struct urr_report_event*>(data));
}

int UrrReportConsumer::HandleEvent(const struct urr_report_event& event) {
  const auto session = session_manager_->GetSession(event.seid);
  if (!session) {
    Logger::upf_app().warn(
        "Dropping URR report for unknown SEID=%" PRIu64, event.seid);
    return 0;
  }
  if (!upf_n4_inst) {
    Logger::upf_app().error(
        "Cannot send URR report for SEID=%" PRIu64 ": N4 is unavailable",
        event.seid);
    return 0;
  }

  pfcp::usage_report_within_pfcp_session_report_request usage_report;
  const pfcp::urr_id_t urr_id    = {.urr_id = event.urr_id};
  const pfcp::ur_seqn_t sequence = {.ur_seqn = ++report_sequences_[event.seid]};
  usage_report.set(urr_id);
  usage_report.set(sequence);
  usage_report.set(ToPfcpTrigger(event.trigger));

  // Usage since the previous report of this SEID
  struct urr_volume& last = last_reported_[event.seid];
  auto since              = [](uint64_t now, uint64_t before) {
    return now >= before ? now - before : now;  // counters were recreated
  };
  struct urr_volume delta = {};
  delta.ul_bytes          = since(event.vol.ul_bytes, last.ul_bytes);
  delta.dl_bytes          = since(event.vol.dl_bytes, last.dl_bytes);
  delta.ul_packets        = since(event.vol.ul_packets, last.ul_packets);
  delta.dl_packets        = since(event.vol.dl_packets, last.dl_packets);
  delta.total_bytes       = delta.ul_bytes + delta.dl_bytes;
  delta.total_packets     = delta.ul_packets + delta.dl_packets;
  last                    = event.vol;

  pfcp::volume_measurement_t volume = {};
  volume.tovol                      = 1;
  volume.ulvol                      = 1;
  volume.dlvol                      = 1;
  volume.tonop                      = 1;
  volume.ulnop                      = 1;
  volume.dlnop                      = 1;
  volume.total_volume               = delta.total_bytes;
  volume.uplink_volume              = delta.ul_bytes;
  volume.downlink_volume            = delta.dl_bytes;
  volume.total_nop                  = delta.total_packets;
  volume.uplink_nop                 = delta.ul_packets;
  volume.downlink_nop               = delta.dl_packets;
  usage_report.set(volume);

  const uint64_t elapsed_ns       = event.timestamp_ns >= event.start_time_ns ?
                                        event.timestamp_ns - event.start_time_ns :
                                        0;
  const uint32_t duration_seconds = SaturatingSeconds(elapsed_ns);
  const uint64_t ntp_now =
      static_cast<uint64_t>(std::time(nullptr)) + kNtpUnixEpochOffset;
  const uint32_t end_seconds = static_cast<uint32_t>(
      std::min<uint64_t>(ntp_now, std::numeric_limits<uint32_t>::max()));
  const uint32_t start_seconds =
      end_seconds >= duration_seconds ? end_seconds - duration_seconds : 0;
  usage_report.set(pfcp::start_time_t{.start_time = start_seconds});
  usage_report.set(pfcp::end_time_t{.end_time = end_seconds});
  usage_report.set(pfcp::duration_measurement_t{.duration = duration_seconds});

  pfcp::pfcp_session_report_request request;
  pfcp::report_type_t report_type = {};
  report_type.usar                = 1;
  request.set(report_type);
  request.set(usage_report);

  upf_n4_inst->send_n4_msg(session->cp_fseid, request);
  Logger::upf_app().info(
      "Queued PFCP Usage Report SEID=%" PRIu64
      " URR_ID=%u UR-SEQN=%u "
      "trigger=0x%02x total_bytes=%" PRIu64,
      event.seid, event.urr_id, sequence.ur_seqn, event.trigger,
      delta.total_bytes);
  return 0;
}

void UrrReportConsumer::PollLoop() {
  while (running_.load()) {
    const int result = ring_buffer__poll(ring_buffer_, 250);
    if (result == -EINTR) continue;
    if (result < 0) {
      Logger::upf_app().error("URR ring buffer polling failed: %d", result);
      break;
    }
    const auto now = std::chrono::steady_clock::now();
    if (now - last_inactivity_check_ >= std::chrono::seconds(1)) {
      last_inactivity_check_ = now;
      FlushPeriodic();
      CheckInactivity();
    }
  }
  running_.store(false);
}

void UrrReportConsumer::FlushPeriodic() {
  if (!volume_map_ || !config_map_ || !upf_n4_inst) return;
  struct timespec ts = {};
  clock_gettime(CLOCK_MONOTONIC, &ts);  // bpf_ktime_get_ns() clock
  const uint64_t now_ns =
      static_cast<uint64_t>(ts.tv_sec) * kNanosecondsPerSecond + ts.tv_nsec;
  for (const auto& session : session_manager_->GetAllSessions()) {
    if (!session) continue;
    uint64_t seid          = session->seid;
    struct urr_config cfg  = {};
    struct urr_volume vol  = {};
    if (config_map_->Lookup(seid, &cfg) != 0) continue;
    if (!(cfg.reporting_triggers & URR_TRIGGER_PERIO) ||
        cfg.measurement_period_ns == 0)
      continue;
    // Grace of half a second: under traffic the datapath reports first
    if (now_ns < cfg.last_report_ns + cfg.measurement_period_ns +
                     kNanosecondsPerSecond / 2)
      continue;
    if (volume_map_->Lookup(seid, &vol) != 0) continue;
    cfg.last_report_ns = now_ns;
    config_map_->Update(seid, cfg, BPF_EXIST);

    struct urr_report_event event = {};
    event.seid                    = seid;
    event.urr_id                  = cfg.urr_id;
    event.trigger                 = URR_TRIGGER_PERIO;
    event.timestamp_ns            = now_ns;
    event.start_time_ns           = cfg.monitoring_time_ns;
    event.vol                     = vol;
    HandleEvent(event);
  }
}

void UrrReportConsumer::CheckInactivity() {
  const auto sessions = session_manager_->GetAllSessions();
  std::unordered_set<uint64_t> live;
  for (const auto& session : sessions)
    if (session) live.insert(session->seid);
  // A reused SEID starts a new session: forget the old one's report state
  for (auto* m : {&report_sequences_}) {
    for (auto it = m->begin(); it != m->end();)
      it = live.count(it->first) ? std::next(it) : m->erase(it);
  }
  for (auto it = last_reported_.begin(); it != last_reported_.end();)
    it = live.count(it->first) ? std::next(it) : last_reported_.erase(it);

  if (!volume_map_ || !upf_n4_inst) return;
  const auto now = std::chrono::steady_clock::now();
  for (const auto& session : sessions) {
    if (!session || session->up_inactivity_timer_s == 0) continue;
    uint64_t seid = session->seid;
    struct urr_volume vol = {};
    if (volume_map_->Lookup(seid, &vol) != 0) continue;  // no URR

    auto [it, inserted] =
        activity_.try_emplace(seid, Activity{vol.total_packets, now, false});
    if (inserted) continue;
    // Any change (including a reset after a usage report) means traffic
    if (vol.total_packets != it->second.packets) {
      it->second = Activity{vol.total_packets, now, false};
      continue;
    }
    if (it->second.reported ||
        now - it->second.last <
            std::chrono::seconds(session->up_inactivity_timer_s))
      continue;

    pfcp::pfcp_session_report_request request;
    pfcp::report_type_t report_type = {};
    report_type.upir                = 1;
    request.set(report_type);
    upf_n4_inst->send_n4_msg(session->cp_fseid, request);
    it->second.reported = true;
    Logger::upf_app().info(
        "Queued PFCP User Plane Inactivity Report SEID=%" PRIu64
        " SUPI=%s (no packet for %u s)",
        seid, session->supi.empty() ? "-" : session->supi.c_str(),
        session->up_inactivity_timer_s);
  }
  for (auto it = activity_.begin(); it != activity_.end();) {
    if (live.count(it->first))
      ++it;
    else
      it = activity_.erase(it);
  }
}
