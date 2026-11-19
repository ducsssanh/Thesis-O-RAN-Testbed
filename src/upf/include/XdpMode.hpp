// SPDX-License-Identifier: LicenseRef-CSSL-1.0
#pragma once
#include <cerrno>
#include <linux/if_link.h>
#include <stdexcept>
#include <string>
namespace upf {
enum class XdpMode { Auto, Skb, Native };
inline XdpMode ParseXdpMode(const std::string& mode) {
  if (mode == "auto") return XdpMode::Auto;
  if (mode == "skb") return XdpMode::Skb;
  if (mode == "native") return XdpMode::Native;
  throw std::invalid_argument("xdp_mode must be auto, skb or native");
}
inline unsigned InitialXdpFlags(XdpMode mode) {
  return mode == XdpMode::Skb ? XDP_FLAGS_SKB_MODE : XDP_FLAGS_DRV_MODE;
}
inline bool ShouldFallbackToSkb(XdpMode mode, int result) {
  return mode == XdpMode::Auto && result == -EOPNOTSUPP;
}
}
