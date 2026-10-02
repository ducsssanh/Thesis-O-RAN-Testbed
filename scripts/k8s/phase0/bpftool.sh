#!/bin/sh
# Read-only BPF inspection of the minikube (docker driver) node from the host.
# The node's glibc is too old for the host bpftool, so run the host binary
# through the host loader inside a throwaway privileged container.
BPFTOOL=${BPFTOOL:-$(ls /usr/lib/linux-tools-*/bpftool | tail -1)}
exec docker run --rm --privileged --pid=host -v /:/host:ro ubuntu:22.04 \
  /host/lib64/ld-linux-x86-64.so.2 --library-path /host/lib/x86_64-linux-gnu \
  "/host$BPFTOOL" "$@"
