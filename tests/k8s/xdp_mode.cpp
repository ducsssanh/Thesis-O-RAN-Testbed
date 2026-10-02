#include "XdpMode.hpp"
#include <cassert>
int main() {
  using namespace upf;
  assert(InitialXdpFlags(ParseXdpMode("skb")) == XDP_FLAGS_SKB_MODE);
  assert(InitialXdpFlags(ParseXdpMode("native")) == XDP_FLAGS_DRV_MODE);
  assert(InitialXdpFlags(ParseXdpMode("auto")) == XDP_FLAGS_DRV_MODE);
  assert(ShouldFallbackToSkb(XdpMode::Auto, -EOPNOTSUPP));
  assert(!ShouldFallbackToSkb(XdpMode::Skb, -EOPNOTSUPP));
  assert(!ShouldFallbackToSkb(XdpMode::Native, -EOPNOTSUPP));
  assert(!ShouldFallbackToSkb(XdpMode::Auto, -EPERM));
  bool rejected=false;
  try { ParseXdpMode("magic"); } catch (const std::invalid_argument&) { rejected=true; }
  assert(rejected);
}
