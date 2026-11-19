/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef SECURITY_API_H_
#define SECURITY_API_H_

/**
 * @file SecurityApi.h
 * @brief UPF Security API: plain HTTP (lab; design 5.3a), own MHD thread.
 *
 *   PUT    /v1/ues/{supi}   {action, ttl_s, rate_ul_kbps?, rate_dl_kbps?,
 *                            epoch?, level?}
 *   DELETE /v1/ues/{supi}
 *   GET    /v1/ues[/{supi}]
 *   GET    /v1/stats[?supi=]
 *   GET    /v1/sessions
 *   GET    /v1/info         (boot_id)
 */

#include <cstdint>

struct MHD_Daemon;

class SecurityApi {
 public:
  static SecurityApi& GetInstance();
  bool Start(uint16_t port);
  void Stop();

 private:
  SecurityApi() = default;
  ~SecurityApi();
  struct MHD_Daemon* daemon_ = nullptr;
};

#endif  // SECURITY_API_H_
