/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#include "SecurityApi.h"

#include <arpa/inet.h>
#include <microhttpd.h>
#include <netinet/in.h>

#include <cstring>
#include <string>

#include "SecurityPolicyStore.h"
#include "logger.hpp"

#if MHD_VERSION < 0x00097002
typedef int MHD_Result;
#endif

using json = nlohmann::json;

namespace {

constexpr size_t kMaxBody = 64 * 1024;

struct Request {
  std::string body;
  bool too_large = false;
};

MHD_Result Send(struct MHD_Connection* c, int status, const json& body) {
  const std::string s = body.dump();
  struct MHD_Response* r = MHD_create_response_from_buffer(
      s.size(), (void*) s.data(), MHD_RESPMEM_MUST_COPY);
  MHD_add_response_header(r, "Content-Type", "application/json");
  MHD_Result ret = MHD_queue_response(c, status, r);
  MHD_destroy_response(r);
  return ret;
}

std::string Peer(struct MHD_Connection* c) {
  const union MHD_ConnectionInfo* ci =
      MHD_get_connection_info(c, MHD_CONNECTION_INFO_CLIENT_ADDRESS);
  if (!ci || !ci->client_addr) return "?";
  char buf[INET6_ADDRSTRLEN] = {0};
  const struct sockaddr* sa  = ci->client_addr;
  if (sa->sa_family == AF_INET)
    inet_ntop(
        AF_INET, &((const struct sockaddr_in*) sa)->sin_addr, buf, sizeof(buf));
  else if (sa->sa_family == AF_INET6)
    inet_ntop(
        AF_INET6, &((const struct sockaddr_in6*) sa)->sin6_addr, buf,
        sizeof(buf));
  return buf;
}

MHD_Result Handle(
    void*, struct MHD_Connection* c, const char* url, const char* method,
    const char*, const char* upload_data, size_t* upload_size, void** con_cls) {
  if (*con_cls == nullptr) {
    *con_cls = new Request();
    return MHD_YES;
  }
  Request* req = static_cast<Request*>(*con_cls);
  if (*upload_size != 0) {
    if (req->body.size() + *upload_size > kMaxBody)
      req->too_large = true;
    else
      req->body.append(upload_data, *upload_size);
    *upload_size = 0;
    return MHD_YES;
  }
  if (req->too_large) return Send(c, 413, {{"error", "body too large"}});

  auto& store       = SecurityPolicyStore::GetInstance();
  const std::string path(url);
  const std::string m(method);
  const std::string ues = "/v1/ues/";
  try {
    if (m == "GET" && path == "/v1/info") return Send(c, 200, store.Info());
    if (m == "GET" && (path == "/v1/ues" || path == "/v1/ues/"))
      return Send(c, 200, store.List());
    if (m == "GET" && path == "/v1/sessions")
      return Send(c, 200, store.Sessions());
    if (m == "GET" && path == "/v1/telemetry") {
      const char* since =
          MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, "since");
      const char* limit =
          MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, "limit");
      const uint64_t s = since ? std::stoull(since) : 0;
      const size_t l   = limit ? std::min<size_t>(std::stoul(limit), 5000) : 1000;
      return Send(c, 200, store.Telemetry(s, l));
    }
    if (path == "/v1/config") {
      if (m == "GET") return Send(c, 200, store.ReflexConfig());
      if (m == "PUT") {
        SecurityPolicyStore::Reply r = store.PutConfig(req->body, Peer(c));
        return Send(c, r.status, r.body);
      }
      return Send(c, 405, {{"error", "method not allowed"}});
    }
    if (m == "GET" && path == "/v1/events") {
      const char* since =
          MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, "since");
      const char* limit =
          MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, "limit");
      const uint64_t s = since ? std::stoull(since) : 0;
      const size_t l   = limit ? std::min<size_t>(std::stoul(limit), 5000) : 1000;
      return Send(c, 200, store.Events(s, l));
    }
    if (m == "GET" && path == "/v1/stats") {
      const char* q =
          MHD_lookup_connection_value(c, MHD_GET_ARGUMENT_KIND, "supi");
      return Send(c, 200, store.Stats(q ? q : ""));
    }
    if (path.rfind(ues, 0) == 0 && path.size() > ues.size()) {
      const std::string supi = path.substr(ues.size());
      SecurityPolicyStore::Reply r = {405, {{"error", "method not allowed"}}};
      if (m == "PUT")
        r = store.Put(supi, req->body, Peer(c));
      else if (m == "DELETE")
        r = store.Delete(supi, Peer(c));
      else if (m == "GET")
        r = store.Get(supi);
      return Send(c, r.status, r.body);
    }
    return Send(c, 404, {{"error", "not found"}});
  } catch (const std::exception& e) {
    return Send(c, 400, {{"error", std::string("bad request: ") + e.what()}});
  }
}

void Completed(
    void*, struct MHD_Connection*, void** con_cls,
    enum MHD_RequestTerminationCode) {
  delete static_cast<Request*>(*con_cls);
  *con_cls = nullptr;
}

}  // namespace

//------------------------------------------------------------------------------
SecurityApi& SecurityApi::GetInstance() {
  static SecurityApi inst;
  return inst;
}

SecurityApi::~SecurityApi() {
  Stop();
}

//------------------------------------------------------------------------------
bool SecurityApi::Start(uint16_t port) {
  if (daemon_) return true;
  daemon_ = MHD_start_daemon(
      MHD_USE_INTERNAL_POLLING_THREAD | MHD_USE_ERROR_LOG, port, nullptr,
      nullptr, &Handle, nullptr, MHD_OPTION_NOTIFY_COMPLETED, &Completed,
      nullptr, MHD_OPTION_CONNECTION_TIMEOUT, (unsigned int) 10,
      MHD_OPTION_END);
  if (!daemon_) {
    Logger::upf_app().error(
        "UPF security: cannot start HTTP API on port %u", port);
    return false;
  }
  Logger::upf_app().info("UPF security: HTTP API listening on port %u", port);
  return true;
}

//------------------------------------------------------------------------------
void SecurityApi::Stop() {
  if (daemon_) MHD_stop_daemon(daemon_);
  daemon_ = nullptr;
}
