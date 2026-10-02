# Runtime gate: URR vào KPM xApp (2026-09-30 UTC)

- Images: `oai-lab-xapp:dc3a036d6734068e` (`sha256:ac5da67dcefbc4e65967ad318f111e12420fb3ef7a3226e774f7842aefc0ab87`), `oai-lab-a1-ei-adapter:22774468a7bcd87e` (`sha256:4fadb2de2fe3f4ee963123e5dc5cd28e366c5d1d8fa82a87244dd867899207ea`).
- `scripts/k8s/lab.sh gate-xapp --fixture`: PASS.
- [Run 20260930T052819Z-m35](../../experiments/20260930T052819Z-m35/ei-correlation.json): UL receiver 157290000 byte/0% loss; DL receiver 157290000 byte/0% loss; PFCP/XDP/KPM, A1-EI và xApp real gates PASS. SEID 1 / UR-SEQN 9 có counter khớp tại PFCP, SMF callback, producer, adapter và xApp. SQLite/export xApp có 20 report thật, 20 event ID duy nhất.
- Restart riêng xApp: 20 report tồn tại trên SQLite/PVC, KPM tiếp tục tăng. Restart riêng adapter: Deployment Ready; report mới SEID 2 / UR-SEQN 27 được ACK và `gate-xapp --real` PASS.
- Scale xApp xuống 0: adapter retry report SEID 2 / UR-SEQN 28, ghi lỗi `connection refused` trong `delivery-status.jsonl` trên PVC. Sau khi scale xApp lên 1, lần thử thứ 7 được ACK HTTP 201; xApp chỉ lưu một bản ghi cho seq 28 và một cho seq 29. Queue không bỏ dữ liệu khi receiver vắng mặt.
- [Run 20260930T053547Z-m35](../../experiments/20260930T053547Z-m35/): UL 157290000 byte/0% loss, DL 157268400 byte/0.014% loss; PFCP/XDP/KPM PASS, A1-EI FAIL. SMF raw callback có SEID 2 / UR-SEQN 1–26 nhưng producer không normalize vì BoltDB đã lưu cùng cặp từ session trước. Đây là va chạm dedup khi SEID được tái sử dụng, không phải lỗi mất traffic hoặc TLS. Cần session epoch xuyên suốt producer → adapter → xApp trong mốc kế tiếp; giữ PVC để tái hiện lỗi.
- Tests: `go test ./...` và `go test -race ./...` cho adapter PASS; `go test ./...` cho producer PASS; `tests/k8s/test_urr_receiver.sh oai-lab-xapp:dc3a036d6734068e` PASS; Helm lint chart Near-RT PASS.

Đường adapter → xApp là interface HTTPS nội bộ của testbed. Gate của run PASS chỉ chứng minh xApp nhận URR và KPM cùng khoảng thời gian; chưa có preprocessing, correlation theo UE hay closed loop.
