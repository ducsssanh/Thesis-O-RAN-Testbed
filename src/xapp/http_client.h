#ifndef OAI_LAB_HTTP_CLIENT_H
#define OAI_LAB_HTTP_CLIENT_H
/* Minimal blocking HTTP/1.0 client of the defense, for the UPF Security API
   (cluster Service, plain HTTP in the lab). url = http://<host>[:port][/path]; the host may be a
   name (getaddrinfo) or an IPv4 address. Returns the response body (free())
   and sets *status, or NULL with err filled. */
#include <stddef.h>

char *http_call(const char *method, const char *url, const char *body, int timeout_ms, int *status, char *err, size_t err_len);
#endif
