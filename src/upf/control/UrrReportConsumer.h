/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef URR_REPORT_CONSUMER_H_
#define URR_REPORT_CONSUMER_H_

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <thread>
#include <unordered_map>

#include "urr_types.h"

struct ring_buffer;
struct urr_report_event;

class BPFMap;
class SessionManager;

/**
 * @brief Bridges URR events from the eBPF dataplane to PFCP/N4.
 *
 * Packet accounting and trigger detection stay in kernel space. This consumer
 * only handles the control-plane work that eBPF cannot perform: resolving the
 * PFCP session, encoding a Usage Report, and handing it to the N4 task.
 */
class UrrReportConsumer {
 public:
  UrrReportConsumer(
      std::shared_ptr<BPFMap> ringbuf_map,
      std::shared_ptr<SessionManager> session_manager,
      std::shared_ptr<BPFMap> volume_map = nullptr,
      std::shared_ptr<BPFMap> config_map = nullptr);
  ~UrrReportConsumer();

  UrrReportConsumer(const UrrReportConsumer&)            = delete;
  UrrReportConsumer& operator=(const UrrReportConsumer&) = delete;

  void Start();
  void Stop();

 private:
  static int OnRingbufEvent(void* context, void* data, size_t data_size);
  int HandleEvent(const struct urr_report_event& event);
  void PollLoop();
  // User Plane Inactivity Report (TS 29.244 5.11.3), session TTL T2: a
  // session with an inactivity timer whose URR packet counter has not moved
  // for that long is reported once, then re-armed by the next packet
  void CheckInactivity();
  // Periodic reporting at the end of each Measurement Period (TS 29.244
  // 5.2.2.2): the XDP program only reports on the next packet, so a period
  // without traffic would be reported late, merged with later ones
  void FlushPeriodic();

  struct Activity {
    uint64_t packets;
    std::chrono::steady_clock::time_point last;
    bool reported;
  };
  std::shared_ptr<BPFMap> volume_map_;
  std::shared_ptr<BPFMap> config_map_;
  std::unordered_map<uint64_t, Activity> activity_;
  // Counters already reported per SEID: the datapath counters are cumulative
  // (quota and thresholds need that), a Usage Report carries the usage since
  // the previous report (TS 29.244 5.2.2.2)
  std::unordered_map<uint64_t, struct urr_volume> last_reported_;
  std::chrono::steady_clock::time_point last_inactivity_check_{};

  std::shared_ptr<BPFMap> ringbuf_map_;
  std::shared_ptr<SessionManager> session_manager_;
  struct ring_buffer* ring_buffer_ = nullptr;
  std::atomic<bool> running_{false};
  std::thread worker_;
  std::unordered_map<uint64_t, uint32_t> report_sequences_;
};

#endif  // URR_REPORT_CONSUMER_H_
