/* see http_client.h */
#include "http_client.h"
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

char *http_call(const char *method, const char *url, const char *body, int timeout_ms, int *status, char *err, size_t err_len) {
  char host[128] = "", path[256] = "/", port[8] = "80";
  int p = 80;
  *status = 0;
  if (sscanf(url, "http://%127[^:/]:%d%255s", host, &p, path) >= 2) {
    snprintf(port, sizeof(port), "%d", p);
  } else if (sscanf(url, "http://%127[^:/]%255s", host, path) < 1) {
    snprintf(err, err_len, "bad URL %s", url);
    return NULL;
  }
  struct addrinfo hints = {.ai_family = AF_INET, .ai_socktype = SOCK_STREAM}, *ai = NULL;
  int g = getaddrinfo(host, port, &hints, &ai);
  if (g != 0 || !ai) {
    snprintf(err, err_len, "resolve %s: %s", host, gai_strerror(g));
    return NULL;
  }
  int fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
  if (fd < 0) {
    freeaddrinfo(ai);
    snprintf(err, err_len, "socket: %s", strerror(errno));
    return NULL;
  }
  struct timeval tv = {.tv_sec = timeout_ms / 1000, .tv_usec = timeout_ms % 1000 * 1000};
  setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
  setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
  char *resp = NULL;
  const size_t bl = body ? strlen(body) : 0;
  if (connect(fd, ai->ai_addr, ai->ai_addrlen) != 0) {
    snprintf(err, err_len, "connect: %s", strerror(errno));
    goto out;
  }
  char head[512];
  int hl = snprintf(head, sizeof(head), "%s %s HTTP/1.0\r\nHost: %s\r\nContent-Type: application/json\r\nContent-Length: %zu\r\n\r\n",
                    method, path, host, bl);
  if (send(fd, head, (size_t)hl, MSG_NOSIGNAL) != hl || (bl && send(fd, body, bl, MSG_NOSIGNAL) != (ssize_t)bl)) {
    snprintf(err, err_len, "send: %s", strerror(errno));
    goto out;
  }
  size_t cap = 4096, len = 0;
  resp = malloc(cap);
  for (;;) {
    if (len + 1 >= cap) {
      if (cap >= 1 << 20) break;
      resp = realloc(resp, cap *= 2);
    }
    ssize_t r = recv(fd, resp + len, cap - len - 1, 0);
    if (r == 0) break;
    if (r < 0) {
      snprintf(err, err_len, "recv: %s", errno == EAGAIN ? "timeout" : strerror(errno));
      free(resp);
      resp = NULL;
      goto out;
    }
    len += (size_t)r;
  }
  resp[len] = '\0';
  if (sscanf(resp, "HTTP/%*s %d", status) != 1) *status = 0;
  char *b = strstr(resp, "\r\n\r\n");
  if (!b) {
    snprintf(err, err_len, "no HTTP body");
    free(resp);
    resp = NULL;
    goto out;
  }
  memmove(resp, b + 4, strlen(b + 4) + 1);
out:
  close(fd);
  freeaddrinfo(ai);
  return resp;
}
