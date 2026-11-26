# Benchmark & Observability Report — Day 14

> Mọi con số lấy từ report JSON / CSV / screenshot thật trong `reports/`, `benchmark-results/`, `screenshots/`.

**Họ tên:** Phung Thi Nhai — 2A202603725
**Ngày chạy:** 2026-11-26
**Môi trường:** ASUS ROG Strix G513IH (16 luồng CPU), Windows 11 + WSL2 Ubuntu, Python 3.11.18, Docker Desktop 4.100.1 (Engine 29.9.3). Agent và load generator chạy trên cùng một máy.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–200 ms/request bình thường; 500 ms chừa đủ chỗ cho retrieval + mạng mà người dùng chat vẫn thấy "tức thì". Đặt theo p95 để 95% người dùng được đảm bảo, không bị average che mất nhóm chậm |
| Error rate `/ask` | < 2 % | Mock LLM có ~1% lỗi upstream (`MOCK_ERROR_RATE=0.01`); 2% = gấp đôi mức nền, vượt ngưỡng nghĩa là có sự cố thật chứ không phải nhiễu |
| Accuracy trên golden dataset | ≥ 80 % (gate merge), mục tiêu 100 % | 80% là quality gate mặc định của `run_eval.py`; sau khi sửa knowledge base v2 đạt 100%, nên không được để thấp hơn baseline (không regression) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

`python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.28 | 190.1 | 219.5 | 1698.3 | 0.33% | ✅ PASS |
| 10 | 38.65 | 189.4 | 218.7 | 1681.7 | 1.33% | ✅ PASS |
| 50 | 106.97 | 198.2 | 268.3 | 1705.6 | 1.67% | ✅ PASS |
| 100 | 71.4 | 355.3 | 3134.8 | 3469.7 | 2.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS gần như tuyến tính từ 1 → 10 (×9, latency p50 không đổi ~190 ms) vì agent xử lý bất đồng bộ (`async def` + `asyncio.sleep`): các request chủ yếu *chờ* LLM nên chồng lên nhau được. Từ 10 → 50 RPS chỉ tăng ×2.8 và p95 bắt đầu nhích lên (268 ms); tới 100 thì RPS **giảm** còn 71.4, p50 gần gấp đôi và p95 vọt lên 3.1 s. Nguyên nhân: agent chạy **1 process uvicorn = 1 event loop trên 1 core**, phần việc CPU (parse JSON, Pydantic, metrics, log) bị xếp hàng; load generator (Python, 100 kết nối song song) chạy cùng máy cũng tranh CPU — thấy rõ khi latency *min* tăng từ ~154 ms lên 198 ms. Muốn tăng tiếp phải scale ngang (nhiều worker/instance), không phải tăng concurrency.

### 2.2 Tail latency

`MOCK_SLOW_RATE=<s>`, `--requests 300 --concurrency 20`, file `reports/load_v2_slow_<s>.json`

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 189.0 | 217.1 | 225.1 |
| 0.03 (mặc định) | 247.2 | 235.8 | 1711.9 |
| 0.1 | 377.4 | 1692.1 | 1710.5 |

**Nhận xét:** Chỉ số nhạy nhất là **p99** (rồi tới p95): với 3% request chậm (+1.5 s), avg chỉ tăng 58 ms (189 → 247) nhưng p99 nhảy từ 225 ms lên **1712 ms**; p95 vẫn ổn vì 3% < 5%. Khi tỉ lệ chậm lên 10% (> 5%), p95 cũng nhảy lên **1692 ms** trong khi avg mới 377 ms — trông vẫn "dưới 500 ms". Average trộn nhóm chậm với số đông nhanh nên che mất trải nghiệm của những người dùng bị chậm; SLO đặt theo p95/p99 mới cam kết được "95%/99% người dùng chờ ít hơn X". Ngoài ra RPS cũng giảm (102 → 60 → 46) vì request chậm giữ chỗ concurrency lâu hơn.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Eval chạy với `MOCK_ERROR_RATE=0` để lỗi upstream ngẫu nhiên không bị tính là câu sai.

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 57.0 | 108.7 | 117.4 |
| Tổng cost (USD) | 0.000402 | 0.000756 | 0.000823 |
| Cost / câu đúng (USD) | 0.00040215 | 0.00003599 | 0.00003577 |
| Quality gate | FAIL (exit 1) | PASS (≥ 80%, 0 regression so với v1) | PASS (≥ 100%, 0 regression so với v2) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | Retrieval không có tài liệu nào khớp nên v2 trả câu generic. Thêm entry `(["jwt"], ...)` vào `KNOWLEDGE_BASE` trong `develop/utils/mock_llm.py`: so sánh API key (chuỗi cố định, không hết hạn) với JWT (token có chữ ký số, chứa user/role/thời điểm hết hạn, không cần tra DB) |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry `(["hpa", "autoscal"], ...)`: HPA scale số pod theo CPU, memory hoặc custom metrics (RPS, queue length, latency từ Prometheus) |

Keyword retrieval chọn hẹp (`jwt`, `hpa`/`autoscal`) để không "giành" tài liệu của các câu đang đúng → eval cuối báo **0 regression**, 2 câu được cải thiện. Không sửa `golden_dataset.jsonl`. Phần sửa cũng được chép sang `production/utils/mock_llm.py`.

Eval cuối:

```text
python eval/run_eval.py --url http://localhost:8002 --min-accuracy 1.0 --baseline reports/eval_v2.json --out reports/eval_v2_fixed.json
Accuracy : 100.0% (23/23) · Câu được cải thiện: 2 · Câu bị regression: 0
Quality gate (accuracy ≥ 100%, không regression): ✅ PASS   → exit code 0
```

**Quality gate trong CI (exit code chặn merge):** `run_eval.py` trả **exit code 1** khi accuracy < `--min-accuracy` hoặc có câu regression so với `--baseline`, ngược lại exit 0. Chạy thử eval v1 với `--baseline reports/eval_v2.json` → 20 câu regression, gate FAIL, **exit code 1**. Trong GitHub Actions, một step trả exit ≠ 0 làm job fail; bật branch protection "require status checks" cho job này thì PR không merge được khi chất lượng tụt:

```yaml
# .github/workflows/eval.yml
name: quality-gate
on: [pull_request]
jobs:
  eval:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: 06-lab-complete/benchmark-observability/develop
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - name: Start agent v2
        run: |
          AGENT_VERSION=v2 MOCK_ERROR_RATE=0 python app.py &
          sleep 3
      - name: Eval + quality gate   # exit 1 → job fail → PR bị chặn
        run: python eval/run_eval.py --url http://localhost:8000 --min-accuracy 0.85 --baseline reports/eval_v2_fixed.json
```

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 thêm bước retrieval và nhét tài liệu vào prompt nên **tốn ~1.9× token mỗi câu** (57 → 108.7) và tổng cost gần gấp đôi, latency p50 tăng nhẹ (~159 → 194 ms trong eval, do thêm bước retrieval ~20 ms). Đổi lại accuracy từ 4.3% lên 91.3% (100% sau khi sửa KB), nên **cost trên mỗi câu đúng rẻ hơn ~11 lần** (0.000402 → 0.000036 USD). So "cost / câu" thì v1 rẻ hơn, nhưng câu trả lời sai là vô giá trị — "cost / câu đúng" phản ánh đúng giá của một câu trả lời hữu ích nên là chỉ số đúng để so hai phiên bản. Sửa KB tăng thêm ~8% token nhưng cost/câu đúng còn giảm nhẹ.

---

## 4. Observability stack (production)

Stack bật bằng `docker compose -p k5-day14-observability up -d --build --scale agent=1` (sau đó scale 3). Lưu ý: Dockerfile có sẵn của `production/` làm agent crash (`ModuleNotFoundError: No module named 'uvicorn'`) vì user `agent` có HOME `/app` nên Python tìm user site ở `/app/.local`, trong khi packages được copy vào `/home/agent/.local`; đã sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`. Lượt benchmark chạy trước khi sửa (100% 502) đã bị bỏ và chạy lại.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals) — [`screenshots/grafana-dashboard.png`](screenshots/grafana-dashboard.png): 15.2 req/s, error rate 20.19%, p95 1.89 s, 3 instance (đang bật A+B; biểu đồ latency thấy rõ bước nhảy lúc 16:43)
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian) — [`screenshots/jaeger-slow-trace.png`](screenshots/jaeger-slow-trace.png): `ec65383…`, 1.7 s, span `chat mock-llm-small` chiếm gần toàn bộ
- [x] Một trace lỗi trong Jaeger (có event `exception`) — [`screenshots/jaeger-error-trace.png`](screenshots/jaeger-error-trace.png): `30ba767…`, `POST /ask` 503, span lỗi đánh dấu ❗; event `exception` xem mục 4.3
- [x] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing** — [`screenshots/prometheus-alert-firing.png`](screenshots/prometheus-alert-firing.png): `AgentHighErrorRate` và `AgentHighLatencyP95` cùng FIRING

### Exercise 7.4 — đọc dashboard (Locust 30 user, 3 instance, cấu hình mặc định)

Câu 1 và 3: số đọc bằng chính PromQL của các panel tại 16:38:03 (cấu hình mặc định). Câu 2: đo lúc 16:47 (đang bật A+B, phân bố tải không phụ thuộc lỗi).

1. **p95 = 292.6 ms, avg = 230.4 ms.** p95 cao hơn avg ~60 ms ở trạng thái bình thường; khoảng cách này là dấu hiệu **tail latency**: phần lớn request ~190 ms nhưng có một nhóm nhỏ (3% request "slow" của LLM, +1.5 s) kéo đuôi phân bố lên. Average trộn nhóm này vào số đông nên trông ổn; khi tỉ lệ chậm tăng (thí nghiệm B) p95 nhảy lên 1898 ms trong khi avg mới 575 ms — khoảng cách càng lớn, càng nhiều user bị chậm mà average không cho thấy.
2. **Nginx chia đều:** panel "Requests/s theo instance" cho 3 instance lần lượt **5.15 / 5.27 / 5.25 req/s** (`sum by (instance) (rate(http_requests_total{route="/ask"}[1m]))`); kiểm tra header `X-Served-By` trước lượt benchmark scale 3 cũng ra 4/4/4 trên 12 request.
3. **Input tokens/s (1471.8) > output tokens/s (784.0)**, gần gấp đôi, vì agent v2 là RAG: prompt gửi lên LLM gồm câu hỏi **cộng tài liệu retrieve được** chèn vào context, nên dài hơn nhiều so với câu trả lời. Ở thí nghiệm E (v1, không retrieval) input tokens/s tụt còn 683.
4. **`curl -i http://localhost:8080/metrics` → `HTTP/1.1 404 Not Found` (Server: nginx).** `nginx.conf` có `location = /metrics` trả 404: endpoint metrics chỉ dành cho Prometheus scrape trực tiếp từng agent trong mạng Docker nội bộ, không public ra ngoài, vì nó lộ thông tin nội bộ (route, version, model, chi phí) và ai cũng gọi được thì tốn tài nguyên.

### 4.2 Thí nghiệm "phá hệ thống"

Cách đo: Locust headless 30 user chạy nền suốt thí nghiệm, 3 instance agent. Đổi biến trong `production/.env` rồi `docker compose -p k5-day14-observability up -d --scale agent=3 agent` (agent được tạo lại); thời gian tính từ lúc lệnh `up` xong tới lúc Prometheus API (`/api/v1/alerts`, poll 5 s, `evaluation_interval: 5s`) báo `state=firing`. A và B bật **cùng lúc** để có 2 alert firing đồng thời (ảnh `screenshots/prometheus-alert-firing.png`). Số metric lấy bằng PromQL ngay sau khi firing.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` | **90 s** (đổi 16:43:37 → firing 16:45:07) | Golden Signals → **Error rate** (0.97% → 20.6%); req/s theo status (5xx) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` | **145 s** (16:43:37 → 16:46:02) | **Latency p50/p95/p99/avg**: p95 292.6 ms → 1898 ms, avg chỉ 230 → 575 ms |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` | **175 s** (đổi 17:10:49 → pending 17:11:44 → firing 17:13:44); đo lại với 10 user, xem ghi chú | **Cost USD/giờ**: $0.80 → $7.01 lúc firing (vẫn đang tăng); latency p95 297 → 695 ms |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (`172.18.0.5:8000`) | **40 s** (16:38:33 → 16:39:13) | **Instances up** 3 → 2; panel Error rate vẫn **xanh** (0.75%) |
| E | `AGENT_VERSION=v1` | **Không có** (theo dõi 3 phút 12 s) | — | **Tokens/s** input 1472 → 683, **Cost/giờ** $5.38 → $1.14, retrieval hit ratio mất, bảng version đổi sang v1; p95 còn giảm (293 → 198 ms) |

Ghi chú:
- **A cần ~90 s** = `rate(...[1m])` cần thời gian để tỉ lệ lỗi trong cửa sổ 1 phút vượt 5% + `for: 1m` ở trạng thái pending. **B cần ~145 s** vì `for: 2m` dài hơn. **D chỉ 40 s** = `for: 30s` + chu kỳ scrape 5 s.
- **D:** `docker pause` (không phải `stop`) để container vẫn còn trong DNS → Prometheus thấy target nhưng scrape fail → `up == 0`. Request Nginx gửi vào instance bị pause chờ tới timeout (504 ở Nginx) — agent chưa từng xử lý chúng nên **metric của agent không đếm**, panel Error rate vẫn xanh. Cần giám sát thêm ở tầng load balancer hoặc synthetic check từ bên ngoài.
- **C:** lần chạy đầu (30 user ≈ 18.8 req/s, model small) cost đã là **$5.38/giờ > ngưỡng $2/giờ** (cửa sổ `rate[5m]` còn chứa cả lượt benchmark 100 user trước đó), nên `LLMCostBurnRateHigh` **đã firing từ trước** khi đổi model — kết quả đó bị bỏ. **Đo lại** với Locust 10 user (6.05 req/s): chờ tới khi cost ổn định ở **$0.80/giờ**, alert inactive, rồi đổi sang `mock-llm-large`. Alert sang pending sau **55 s** (cửa sổ `rate[5m]` mới tích đủ chi phí model lớn để vượt $2/giờ) và firing sau **175 s** (= 55 s + `for: 2m`). Lúc firing cost đã $7.01/giờ (×8.8) và vẫn đang tăng vì `rate[5m]` còn trộn dữ liệu model nhỏ; model lớn đắt hơn ~16 lần và chậm hơn ~2.5 lần nên p95 cũng tăng gấp đôi. Bài học: ngưỡng cost theo burn rate tuyệt đối phụ thuộc lưu lượng — ở 30 user model nhỏ đã vượt $2/giờ, nên trong production nên alert theo **chi phí / request** hoặc theo % budget ngày thay vì một ngưỡng cố định.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi sang v1 làm accuracy rơi từ 100% xuống 4.3% (theo eval ở mục 3) nhưng mọi metric hạ tầng lại **đẹp hơn**: latency giảm, error rate không đổi, cost giảm. Observability hạ tầng chỉ trả lời "hệ thống có chạy không", không trả lời "câu trả lời có đúng không". Cách phát hiện:
1. **Chặn trước khi deploy:** chạy `run_eval.py` với golden dataset + `--baseline` trong CI; exit code 1 khi accuracy giảm hoặc có regression → không merge/deploy được (bản v1 sẽ bị chặn với 20 câu regression).
2. **Giám sát chất lượng khi chạy:** chạy eval định kỳ (canary/synthetic) trên production và đẩy accuracy thành metric để alert; theo dõi metric proxy như **retrieval hit ratio**, **tokens/câu** (đều tụt mạnh ở E) và alert khi lệch khỏi baseline; thu thập feedback người dùng (👍/👎) hoặc dùng LLM-as-judge trên một tỉ lệ mẫu request.
3. **Alert khi version đổi bất thường** (`agent_info{version}`) để người trực biết có deploy vừa xảy ra.

### 4.3 Debug bằng trace

Trace chậm nhất trong 1500 trace gần nhất (Jaeger, service `observable-agent`, ảnh `screenshots/jaeger-slow-trace.png`):

- `trace_id`: `ec653832d9b6e88d1e91f570a732e329`
- Tổng thời gian: **1741.9 ms** (`POST /ask`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1675.5 ms, 96.2%**) — `gen_ai.request.model=mock-llm-small`, `input_tokens=95`, `output_tokens=55`

```text
POST /ask                    1741.9 ms (100.0%)
└─ agent.run                 1692.2 ms ( 97.1%)
   ├─ agent.retrieve_context   16.4 ms (  0.9%)
   └─ chat mock-llm-small    1675.5 ms ( 96.2%)   ← LLM chậm, không phải code của agent
```

- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep ec653832d9b6e88d1e91f570a732e329`):

```json
{"ts": "2026-11-26T09:47:05.241370+00:00", "level": "INFO", "service": "observable-agent", "instance": "6f26c0685cb7", "event": "llm_call", "trace_id": "ec653832d9b6e88d1e91f570a732e329", "span_id": "89c81e937ed9fa56", "request_id": "fc252a487746", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1675.1}
{"ts": "2026-11-26T09:47:05.241986+00:00", "level": "INFO", "service": "observable-agent", "instance": "6f26c0685cb7", "event": "http_request", "trace_id": "ec653832d9b6e88d1e91f570a732e329", "span_id": "89c81e937ed9fa56", "request_id": "fc252a487746", "method": "POST", "route": "/ask", "status": 200, "ms": 1741.2}
```

Log ghi `llm_ms: 1675.1` khớp với span `chat` 1675.5 ms → xác nhận thời gian nằm ở upstream LLM. Hướng xử lý: timeout + retry/hedged request cho LLM, không phải tối ưu code agent.

**Trace lỗi** (ảnh `screenshots/jaeger-error-trace.png`): `trace_id` `30ba767bb22f73c30bfe90d425213791`, 124.6 ms, span `chat mock-llm-small` có status ERROR, `error.type=upstream_unavailable` và event **`exception`** (`utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`), lan lên `agent.run` và `POST /ask` → client nhận 503. Log khớp:

```json
{"ts": "2026-11-26T09:47:12.650824+00:00", "level": "INFO", "service": "observable-agent", "instance": "6442edd2f663", "event": "llm_error", "trace_id": "30ba767bb22f73c30bfe90d425213791", "span_id": "f176263a5e4c7d1a", "request_id": "d10ed8d7d8a1", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
{"ts": "2026-11-26T09:47:12.651127+00:00", "level": "INFO", "service": "observable-agent", "instance": "6442edd2f663", "event": "http_request", "trace_id": "30ba767bb22f73c30bfe90d425213791", "span_id": "f176263a5e4c7d1a", "request_id": "d10ed8d7d8a1", "method": "POST", "route": "/ask", "status": 503, "ms": 123.9}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

`docker compose -p k5-day14-observability run --rm locust ... --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_<n>` — số liệu dòng **Aggregated** trong `benchmark-results/scale_<n>_stats.csv` (trong ngoặc: riêng `POST /ask`).

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 65.54 (`/ask` 59.38) | 190 | 230 | 1700 | 57 / 7836 (0.73%) — đều là 503 từ mock LLM |
| 3 | 66.41 (`/ask` 60.32) | 190 | 220 | 1700 | 62 / 7939 (0.78%) — đều là 503 từ mock LLM |

Trước khi chạy scale 3 đã kiểm tra 12 request qua Nginx: header `X-Served-By` chia đều 4/4/4 cho 3 IP agent → load balancer hoạt động.

**Giải thích kết quả:** Scale 1 → 3 instance **gần như không đổi** RPS (+1.3%), p50 và p99 y hệt, p95 chỉ khác 10 ms (nằm trong độ phân giải của Locust). Hai lý do:

1. **Nút thắt là latency của LLM (upstream), không phải CPU của agent.** Mỗi request chủ yếu *chờ* mock LLM (~120 ms + retrieval, 3% chậm thêm 1.5 s) bằng `asyncio.sleep`; một instance async đã chồng được hàng trăm request đang chờ nên chưa bão hoà. Thêm instance không làm LLM trả lời nhanh hơn → p50 ≈ 190 ms và p99 ≈ 1700 ms (chính là request "slow" của LLM) giữ nguyên. Panel LLM latency trong Grafana phản ánh đúng điều này.
2. **Tải của Locust là closed-loop:** 100 user, mỗi user chờ 0.5–2 s giữa các request → trần lý thuyết ≈ 100 / (1.25 s + 0.21 s) ≈ 68 req/s, khớp với ~66 req/s đo được. Hệ thống đã phục vụ hết tải được sinh ra, nên thêm instance không có thêm việc để làm.

Scale ngang chỉ có ích khi instance bị bão hoà (CPU/RAM, `agent_in_flight_requests` cao). Muốn giảm tail latency ở đây phải xử lý phía LLM: timeout + retry/hedging cho request chậm, cache câu trả lời, hoặc model nhanh hơn.

---

## 6. Kết luận

- 3 điều học được về benchmark & observability:
  1. **Average nói dối, percentile thì không.** Với 3% request chậm, avg chỉ tăng 58 ms nhưng p99 nhảy từ 225 ms lên 1712 ms; với 10% thì avg vẫn < 400 ms trong khi p95 đã 1.7 s. SLO và alert phải đặt theo p95/p99, và load test phải đủ mẫu (300 request) — 23 câu eval không đủ để kết luận về latency.
  2. **Hạ tầng xanh ≠ agent đúng.** Đổi sang v1 làm accuracy rơi từ 100% xuống 4.3% nhưng không alert nào kêu, thậm chí latency và cost còn đẹp hơn. Chất lượng phải được chặn bằng eval + quality gate trong CI (exit code) và giám sát bằng metric chất lượng (retrieval hit ratio, tokens/câu, eval định kỳ). So sánh phiên bản bằng "cost / câu đúng" chứ không phải "cost / câu".
  3. **Ba trụ cột phải nối với nhau và đo đúng chỗ.** Dashboard báo p95 tăng → Jaeger chỉ ra 96% thời gian nằm ở span LLM → `trace_id` trong log JSON cho chi tiết (`llm_ms`, model, tokens). Đồng thời metric chỉ thấy những gì service đó xử lý: instance bị pause làm Nginx trả 504 nhưng panel Error rate của agent vẫn xanh; scale 3 instance không giúp gì khi nút thắt là upstream LLM.
- Nếu đưa agent này lên production thật, sẽ thêm metric / alert nào nữa?
  - **Chất lượng:** metric `agent_eval_accuracy` từ eval định kỳ (canary) + alert khi giảm so với baseline; `retrieval_hit_ratio` và tokens/câu lệch khỏi baseline; tỉ lệ feedback 👎 từ người dùng.
  - **Tầng ngoài:** synthetic check từ bên ngoài gọi `/ask` mỗi phút, và metric 5xx/504 + latency ở Nginx/load balancer (bắt được lỗi mà agent không thấy như thí nghiệm D).
  - **SLO burn rate:** alert multi-window (vd 1h và 6h) theo error budget thay cho ngưỡng cố định, giảm alert fatigue.
  - **Saturation & phụ thuộc:** `agent_in_flight_requests` cao kéo dài, Redis/LLM timeout rate, tỉ lệ request bị rate limit (429) và cost guard (402).
  - **Chi phí:** budget theo ngày/tháng (đã đạt bao nhiêu % budget) thay cho chỉ burn rate; cảnh báo khi model đổi bất thường (`agent_info{model}`).
