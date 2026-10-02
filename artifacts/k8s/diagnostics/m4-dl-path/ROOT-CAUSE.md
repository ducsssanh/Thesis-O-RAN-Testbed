# DL iperf diagnosis (2026-09-29)

Mốc 4 DL receiver is empty because packets are lost at two different points.
The sender CSV is evidence of bytes *sent*, not bytes received.

1. The original iperf2 command uses its default 1470-byte UDP datagram. Each
   sender interval is an exact multiple of 1470 bytes (for example 66,150 =
   45 × 1470). With 28 bytes of inner IPv4/UDP and 44 bytes of outer
   IPv4/UDP/GTP-U/PDU Session Container, this creates a 1542-byte outer IP
   packet on an N3 interface with MTU 1500. During the original test, UPF N6
   RX rose but UPF N3 TX did not rise with the data traffic.

2. A controlled five-second test with `iperf -l 1200` removed that size
   problem. The sender transmitted 324,000 bytes. UPF N3 TX increased from
   7,064 to 611,568 bytes, and gNB N3 RX reached 606,614 bytes / 497 packets.
   gNB LCID 4 TX rose to 580,630 bytes. UE `oaitun_ue1` RX remained 0, and
   the receiver timed out without a CSV result. See `sender-1200.csv`,
   `receiver-1200.csv`, `n3-before-1200.txt`, `n3-after-1200.txt`.

3. gNB logs show the bearer was configured for QFI 1. UPF's session display
   shows no QER/QFI for the downlink PDR. A prior PFCP capture at
   `artifacts/k8s/diagnostics/m35-live-urr-ran-restart.pcap` confirms the
   SMF sent QFI 1 on the uplink PDR but no QFI on the subsequently created
   downlink PDR. In the eBPF source, `match_pdr_n6`
   takes QFI from `pdi.qfi` (zero when absent), and `gtpu_encap_ipv4` puts that
   value into the PDU Session Container. The gNB SDAP code falls back to the
   default DRB when QFI 0 is unmapped but checks the *QFI 0 mapping's* role;
   it then forwards the IP packet to PDCP without an SDAP header. The UE has
   SDAP enabled and interprets the first octet of the IPv4 packet (0x45) as
   QFI 5 (`0x45 & 0x3f == 5`). Its log repeatedly says `Dropping UL SDAP PDU
   with unmapped QFI=5`; that log string is also used in its DL receive path.
   This explains why gNB's radio TX rose while UE TUN RX stayed zero.

The QFI/SDAP explanation was a code-and-log inference; a live N3 packet
capture of the PDU Session Container would make it direct wire-level proof.
The subsequent UPF image `oai-lab-upf:qfi-f6d0516adf20` logs that it derives
QFI 1 from the unique ACCESS PDR in the same session. With that image and
1200-byte iperf datagrams, DL packets reached UE `oaitun_ue1`, but the UDP
receiver was still empty.

The remaining failure was the inner UDP checksum. For the five-second DL test
on port 5111, UE TUN RX increased by 470 packets and `/proc/net/snmp` UDP
`InCsumErrors` increased from 479 to 949, also by 470. The DN N6 veth had TX
checksum offload enabled. Disabling it with `ethtool -K n6 tx off` in the DN
network namespace made the next DL test (port 5113) deliver all 324000 bytes
to the UE iperf receiver with zero packet loss and no additional checksum
errors. This is a lab-scoped mitigation for the XDP-SKB path forwarding
CHECKSUM_PARTIAL packets without completing the inner checksum.

The mitigation is now persistent in the core chart: DN's init container runs
`ethtool -K n6 tx off` before the main container. After Helm release revision
14 restarted DN, its init log confirmed `tx-checksum-ip-generic: off`. A fresh
port-5115 test again received 324000/324000 bytes, zero loss; UE
`InCsumErrors` stayed at 949. The sender CSV alone is not acceptance evidence;
the UE receiver CSV and checksum counter are.

These short tests establish UL/DL reachability. They do not establish Mốc 4
end-to-end acceptance: the 120-second traffic, real URR through SMF/A1-EI,
KPM overlap, restart and persistence gates remain.

An end-to-end `scripts/k8s/lab.sh experiment` was started after the DL fix and
the RAN/E2/KPM gate passed. During the 120-second UL phase, host package
temperature reached 100–101°C, so the run was interrupted to avoid another
host crash. The iperf processes and PFCP capture were stopped; gNB, UE and
xApp were scaled to zero. No Mốc 4 PASS is claimed from this interrupted run.
Before retrying the planned 10 Mbit/s × 120-second UL/DL experiment, improve
host cooling or use a host with sufficient thermal headroom, then run
`scripts/k8s/lab.sh up --stage ran` followed by `scripts/k8s/lab.sh experiment`.
