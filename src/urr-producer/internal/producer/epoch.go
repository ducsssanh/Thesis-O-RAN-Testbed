package producer

import (
	"fmt"
	"strconv"
	"time"
)

// SEID alone does not identify a PDU session: the OAI SMF restarts its SEID
// counter when it restarts, so a new session can reuse SEID and UR-SEQN of an
// old one. A session epoch tells them apart. OAI reports Duration and Volume
// cumulatively from the start of the session, so smf_timestamp - Duration is
// the session start time (to within the 1 s resolution of both fields) and is
// stable over every report of one session.

// epochTolerance is the largest start-time jitter accepted within one
// session. A reused SEID only appears after an SMF restart, so two sessions
// sharing a SEID start far more than this apart.
const epochTolerance = 3 // seconds

// ntpUnixOffset converts NTP seconds (OAI smf_timestamp) to Unix seconds.
const ntpUnixOffset = 2208988800

type epochState struct {
	Epoch     string `json:"epoch"`
	LastStart int64  `json:"last_start"`
	LastSeq   uint64 `json:"last_seq"`
}

// sessionStart estimates the Unix start time of the session that produced v.
func sessionStart(v Normalized, now time.Time) int64 {
	at := now.Unix()
	if ts, err := strconv.ParseInt(v.SMFTimestamp, 10, 64); err == nil && ts > ntpUnixOffset {
		at = ts - ntpUnixOffset
	}
	return at - int64(v.DurationSeconds)
}

func formatEpoch(start int64) string {
	return time.Unix(start, 0).UTC().Format("20060102T150405Z")
}

// fingerprint is the report content compared when a (SEID, epoch, UR-SEQN)
// key is seen again: equal means a retransmission, different means another
// session that reused the key.
func fingerprint(v Normalized) string {
	return fmt.Sprintf("%d/%d/%d/%d/%d", v.DurationSeconds, v.ULBytes, v.DLBytes, v.ULPackets, v.DLPackets)
}

// assignEpoch decides the epoch of a report. prev is the current epoch of
// (SUPI, SEID), nil if none; stored is the fingerprint already recorded for
// (SEID, prev.Epoch, seq), "" if none. It returns the epoch, whether the
// report is a duplicate, and the next state.
func assignEpoch(prev *epochState, start int64, seq uint64, fp, stored string) (string, bool, epochState) {
	if prev != nil {
		if stored == fp {
			return prev.Epoch, true, *prev
		}
		delta := start - prev.LastStart
		if delta < 0 {
			delta = -delta
		}
		if stored == "" && delta <= epochTolerance {
			next := *prev
			next.LastStart = start
			if seq > next.LastSeq {
				next.LastSeq = seq
			}
			return prev.Epoch, false, next
		}
	}
	epoch := formatEpoch(start)
	for prev != nil && epoch == prev.Epoch {
		start++
		epoch = formatEpoch(start)
	}
	return epoch, false, epochState{Epoch: epoch, LastStart: start, LastSeq: seq}
}
