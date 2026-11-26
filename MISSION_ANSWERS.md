# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Secret hardcode trong code:** `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@..."`. Push lên GitHub là lộ key, và đổi key phải sửa code + deploy lại.
2. **Log ra secret:** `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` — khi chạy thật, log in nguyên key (xem output 1.2). Log thường được gửi sang hệ thống khác nên secret lan ra ngoài.
3. **`print()` thay cho logging có cấu trúc:** không có level, timestamp, không parse được bằng log aggregator; lẫn với log của uvicorn.
4. **Không có health check:** `GET /health` trả **404** (output 1.2) → platform không biết agent còn sống để restart.
5. **Host/port cứng:** `host="localhost"`, `port=8000` — trong container chỉ nghe loopback nên bên ngoài không gọi được; Railway/Render cấp `PORT` qua env nhưng app bỏ qua.
6. **`reload=True` và `DEBUG = True` cố định:** chế độ dev (theo dõi file, tự reload) chạy cả ở production, tốn tài nguyên và dễ lộ thông tin debug.
7. **Không xử lý shutdown:** không có lifespan/cleanup; khi platform gửi SIGTERM, request đang chạy có thể bị cắt ngang.
8. **Config không quản lý tập trung:** `MAX_TOKENS = 500` hằng số trong code, không đổi được theo môi trường.

### Exercise 1.2: Chạy bản develop

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
server: uvicorn
content-type: application/json

{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}

$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
{"detail":"Not Found"}
```

Log server (secret bị in ra):

```text
Uvicorn running on http://localhost:8000 (Press CTRL+C to quit)
Started reloader process [2214] using WatchFiles
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this
```

Chạy được, nhưng chưa production-ready: lộ secret, không health check, chỉ nghe `localhost`, bật reloader.

### Exercise 1.3: So sánh develop ↔ production

Bản production chạy thật: `/health` → 200 `{"status":"ok","uptime_seconds":0.4,...}`, `/ready` → 200 `{"ready":true}`, `POST /ask` (JSON) → 200; gửi SIGTERM → log `Shutting down → Waiting for application shutdown → Application shutdown complete`.

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hằng số trong code (`DEBUG=True`, `MAX_TOKENS=500`) | `config.py` đọc env (`os.getenv`), `validate()` fail-fast khi thiếu `AGENT_API_KEY` ở production | Cùng một image chạy được ở dev/staging/prod chỉ bằng đổi env; sai config bị phát hiện lúc khởi động thay vì lúc có user |
| Secrets | Hardcode + in ra log | Đọc từ env, không log secret (chỉ log `question_length`) | Secret không nằm trong Git/log; rotate key không cần sửa code |
| Health check | Không có (`/health` 404) | `/health` (liveness) + `/ready` (readiness) | Platform/LB biết khi nào restart container và khi nào được gửi traffic vào |
| Logging | `print()` | Logging có level, nội dung dạng JSON | Parse/tìm kiếm được trong Loki/Datadog, lọc theo level, không lẫn secret |
| Shutdown | Đột ngột | `lifespan` dọn dẹp, uvicorn chờ request đang chạy | Không cắt ngang request, không mất dữ liệu khi deploy/scale |
| Host/Port | `localhost:8000` cứng | `0.0.0.0` + `PORT` từ env | Container nhận được kết nối từ ngoài; platform tự cấp port |
| Reload/debug | `reload=True` luôn bật | Chỉ reload khi `DEBUG=true` | Tránh overhead và lộ thông tin debug trong production |

**Quan sát thêm khi chạy:** trong bản production, các dòng log JSON của app và handler `handle_sigterm` tự viết **không xuất hiện** trong log, vì `uvicorn.run()` cấu hình lại logging và cài signal handler của chính nó, ghi đè handler của app. Graceful shutdown vẫn đúng vì uvicorn tự xử lý SIGTERM — đây cũng là lý do Part 6 dùng `lifespan` thay vì tự đăng ký handler SIGTERM.

## Part 2: Docker

### Exercise 2.1: Dockerfile cơ bản (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11` — bản Python đầy đủ (Debian + build tools), nên image rất nặng (1.67 GB đo được ở 2.3).
2. **Working directory:** `/app` (`WORKDIR /app`) — mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy trong thư mục này.
3. **Vì sao `COPY requirements.txt` trước:** Docker cache theo từng layer. Requirements ít thay đổi, code thay đổi liên tục; copy và `pip install` requirements trước thì khi chỉ sửa code, layer cài dependencies được dùng lại từ cache, build nhanh hơn rất nhiều. Nếu `COPY . .` trước thì mỗi lần sửa code đều phải cài lại toàn bộ thư viện.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số mặc định, bị ghi đè khi `docker run image <lệnh khác>`; `ENTRYPOINT` là chương trình cố định luôn chạy, tham số của `docker run` được nối thêm vào sau. Hay dùng `ENTRYPOINT` cho executable và `CMD` cho tham số mặc định.

### Exercise 2.2: Build và run (build từ gốc repo)

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -d -p 8000:8000 my-agent:develop
$ curl -i -X POST "http://localhost:8000/ask?question=What%20is%20Docker"
HTTP/1.1 200 OK
server: uvicorn
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}

$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.6,"container":true}
```

### Exercise 2.3: Multi-stage build — kích thước image

- **Stage 1 (`builder`, `python:3.11-slim`):** cài `gcc`, `libpq-dev` rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này có build tools nhưng **không** được dùng để deploy.
- **Stage 2 (`runtime`, `python:3.11-slim`):** chỉ copy `/root/.local` (thư viện đã cài) và code sang, tạo user `appuser` non-root, có `HEALTHCHECK`, chạy `uvicorn --workers 2`.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc, header, apt cache, pip cache; base `slim` thay vì bản đầy đủ.

```text
$ docker images my-agent
REPOSITORY   TAG        SIZE
my-agent     advanced   240MB
my-agent     develop    1.67GB
```

- Develop: **1667.8 MB** (1 667 784 054 bytes)
- Production: **239.8 MB** (239 815 429 bytes)
- Chênh lệch: **giảm 85.6%** ((1667.8 − 239.8) / 1667.8)

### Exercise 2.4: Docker Compose stack

```text
                 ┌────────────────────── network "internal" (bridge) ──────────────────────┐
 Client ──:80──▶ │ nginx (reverse proxy, LB, rate limit 10r/s, security headers)           │
                 │   └──▶ agent:8000 (FastAPI, uvicorn 2 workers, healthcheck /health)      │
                 │          ├──▶ redis:6379  (session cache / rate limit, healthcheck ping) │
                 │          └──▶ qdrant:6333 (vector DB cho RAG, healthcheck tcp)           │
                 └──────────────────────────────────────────────────────────────────────────┘
```

- Chỉ **nginx** mở cổng ra host (80/443); agent, redis, qdrant chỉ nằm trong network `internal`, gọi nhau bằng tên service (DNS của Docker).
- `agent` `depends_on` redis + qdrant với `condition: service_healthy` → chỉ khởi động khi hai service kia healthy.

Chạy bằng `docker compose -p k5-day14-docker up -d --build`:

```text
SERVICE   IMAGE                   STATUS                            PORTS
agent     k5-day14-docker-agent   Up 2 seconds (health: starting)   8000/tcp
nginx     nginx:alpine            Up 2 seconds                      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 13 seconds (healthy)           6333-6334/tcp
redis     redis:7-alpine          Up 13 seconds (healthy)           6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":1.3,"version":"2.0.0","timestamp":"2026-11-26T09:11:17.119380"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

Response đi qua Nginx (header `Server: nginx` + các security header do Nginx thêm), log agent ghi `{"event": "request", "q_len": 21}`.

## Part 3: Cloud Deployment

K5 deploy chính agent Part 6 (`06-lab-complete/`) thay vì app mẫu trong `03-cloud-deployment/`.

### Exercise 3.2 — Deploy Render (nền tảng chính)

- **URL:** https://day14-agent-8wjd.onrender.com
- **Cách deploy:** Render Dashboard → New → Blueprint → chọn repo, Blueprint Path `06-lab-complete/render.yaml` → nhập `AGENT_API_KEY` → Deploy Blueprint. Render tạo web service `day14-agent` (Docker) và Key Value `day14-redis`.
- **Kết quả 4 lệnh tự kiểm (CP6):** `/health` 200 · `/ready` 200 · `/ask` không key 401 · `/ask` có key 200. Chi tiết và ảnh: [DEPLOYMENT.md](DEPLOYMENT.md).

### So sánh `railway.toml` với `render.yaml`

Cả hai file đều có trong [`06-lab-complete/`](06-lab-complete/) và đều qua script chấm.

| | `railway.toml` | `render.yaml` |
|---|---|---|
| Phạm vi | Cấu hình **build + deploy của 1 service** (builder, healthcheck, restart policy) | **Blueprint cả hạ tầng**: khai báo web service *và* Redis (Key Value) trong cùng file |
| Build | `builder = "DOCKERFILE"`, `dockerfilePath` | `runtime: docker`, `rootDir`, `dockerContext`, `dockerfilePath` |
| Health check | `healthcheckPath = "/health"` | `healthCheckPath: /health` |
| Biến môi trường | Không nằm trong file; đặt bằng `railway variables` hoặc dashboard | Khai báo trong `envVars`; secret dùng `sync: false` (nhập tay) hoặc `generateValue: true` |
| Redis | Thêm database Redis vào project riêng, rồi tham chiếu `${{Redis.REDIS_URL}}` | `fromService` → `connectionString` của Key Value khai báo ngay trong file |
| Vị trí file | Đọc từ thư mục được `railway up` | Mặc định ở gốc repo; ở thư mục con phải chỉ Blueprint Path và đặt `rootDir` |
| PORT | Platform cấp, app đọc `${PORT:-8000}` | Như Railway |

**Vì sao khác:** Railway thiên về CLI và dashboard — file chỉ mô tả cách build/chạy, còn tài nguyên (Redis) và biến được tạo bằng lệnh hoặc giao diện. Render Blueprint là Infrastructure-as-Code: mọi tài nguyên và cách nối chúng nằm trong một file được sync từ Git, nên tái tạo được toàn bộ stack từ repo, đổi lại file dài hơn và phải khai báo cả Redis.

### Exercise 3.3 — GCP Cloud Run CI/CD (đọc `cloudbuild.yaml`, `service.yaml`)

1. Cloud Build được trigger khi push lên `main`; bước **test** chạy `pytest` trong image `python:3.11-slim` — test fail thì pipeline dừng, không build.
2. Bước **build** tạo Docker image gắn 2 tag (`$COMMIT_SHA` và `latest`), dùng `--cache-from latest` để tận dụng layer cache; bước **push** đẩy image lên Container Registry.
3. Bước **deploy** chạy `gcloud run deploy` với image tag theo commit (rollback được), region `asia-southeast1`, `min-instances=1` (tránh cold start), `max-instances=10`, 512Mi/1 CPU, secret lấy từ **Secret Manager** (`--set-secrets`) thay vì hardcode.
4. `service.yaml` mô tả cùng service dạng khai báo (Knative): autoscaling 1–10 instance, `containerConcurrency: 80`, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`, `AGENT_API_KEY`/`OPENAI_API_KEY` đọc từ `secretKeyRef`.

## Part 4: API Security

### Exercise 4.1: API Key (`04-api-gateway/develop`, chạy `AGENT_API_KEY=secret-key-123 python app.py`)

- **Key được check ở đâu:** dependency `verify_api_key()` dùng `APIKeyHeader(name="X-API-Key", auto_error=False)`, gắn vào `/ask` bằng `Depends(verify_api_key)`. Key so với biến môi trường `AGENT_API_KEY`.
- **Sai key thì sao:** thiếu key → **401**, sai key → **403** (bản này tách hai trường hợp; Part 6 yêu cầu cả hai đều 401).
- **Rotate key:** đổi giá trị `AGENT_API_KEY` trên platform rồi restart — không sửa code. Muốn không gián đoạn thì cho phép tạm thời cả key cũ và key mới (danh sách key), báo client đổi xong mới bỏ key cũ.

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`)

Flow: `POST /auth/token` với username/password → server ký JWT (HS256, payload `sub`, `role`, `iat`, `exp` 60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm chữ ký + hạn, lấy `username`/`role` mà **không cần tra database** mỗi request (stateless). Token hết hạn → 401, token sai chữ ký → 403.

```text
$ curl -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
{"access_token":"<TOKEN_REDACTED>","token_type":"bearer","expires_in_minutes":60,...}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer <TOKEN_REDACTED>" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. ...","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting

- **Thuật toán:** sliding window — mỗi user có một `deque` timestamp; mỗi request xoá timestamp cũ hơn 60s rồi đếm.
- **Giới hạn:** `student` (role user) **10 request/phút**; admin 100 request/phút.
- **Bypass cho admin:** không bỏ qua hẳn mà dùng limiter riêng `rate_limiter_admin` (100/phút) khi `role == "admin"` (user `teacher`).

Vòng lặp 15 request dùng cùng token (request "Explain JWT" phía trên đã tính là request thứ 1 trong cửa sổ):

```text
request  1 -> 200   ...   request  9 -> 200
request 10 -> 429   ...   request 15 -> 429

$ curl -i ... (request thứ 16)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

→ 10 request thành công trong 60 giây, request thứ 11 bị 429 kèm `Retry-After`.

### Exercise 4.4: Cost guard

Cách `cost_guard.py` làm:
1. **Trước** khi gọi LLM: `check_budget(user)` — tổng chi phí trong ngày của user ≥ **$1/ngày** → **402 Payment Required**; tổng toàn hệ thống ≥ **$10/ngày** → 503; dùng ≥ 80% budget → log cảnh báo.
2. **Sau** khi gọi LLM: `record_usage(user, input_tokens, output_tokens)` tính tiền theo giá token (input $0.15/1M, output $0.60/1M) và cộng dồn.
3. **Reset:** bản ghi gắn với ngày (`day = YYYY-MM-DD`); sang ngày mới tạo bản ghi mới → budget về 0.

Ví dụ thật sau 10 request: `/me/usage` → `{"requests":10,"input_tokens":40,"output_tokens":292,"cost_usd":0.000181,"budget_usd":1.0,...}`.

Hạn chế và cách Part 6 sửa: state lưu **trong RAM** → chạy nhiều instance/worker thì mỗi process có bộ đếm riêng, restart là mất. Ở Part 6 mình lưu tổng chi phí trong **Redis** (`INCRBYFLOAT cost:daily:<ngày>` + `EXPIRE` 2 ngày) để mọi instance dùng chung và vẫn còn sau restart. (Nhận xét nhỏ: field `budget_remaining_usd` trong response `/ask` của bản mẫu thực ra trả về chi phí **đã dùng**, không phải phần còn lại.)

**Rate limit vs cost guard:** rate limit bảo vệ **tốc độ** (số request/phút — chống spam, DoS, một client chiếm hết tài nguyên); cost guard bảo vệ **tiền** (tổng chi phí token theo ngày/tháng). Cần cả hai vì một user có thể gửi ít request nhưng mỗi request rất đắt (prompt dài, model lớn) — rate limit không chặn được; ngược lại cost guard không chặn được hàng nghìn request rẻ làm quá tải server.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

```text
$ curl -i http://localhost:8000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":0.6,"version":"1.0.0","environment":"development",...,"checks":{"memory":{"status":"ok","used_percent":17.1}}}

$ curl -i http://localhost:8000/ready
HTTP/1.1 200 OK
{"ready":true,"in_flight_requests":1}
```

**`/health` (liveness) khác `/ready` (readiness):**
- `/health` trả lời "process còn sống không?" — chỉ phụ thuộc chính process. Fail → platform **restart** container.
- `/ready` trả lời "có nhận traffic được chưa?" — kiểm tra phụ thuộc (Redis, DB, model đã load, đang shutdown…). Fail (503) → load balancer **ngừng gửi request** vào instance đó nhưng không giết nó.
- Nếu gộp hai cái: Redis chập chờn → liveness fail → platform restart hàng loạt container dù process vẫn khoẻ, làm sự cố tệ hơn. Vì vậy ở Part 6, `/health` luôn 200 còn `/ready` trả 503 khi mất Redis.

### Exercise 5.2: Graceful shutdown

Gửi một request rồi `kill -TERM` process ngay sau 50 ms:

```text
[in-flight request] HTTP 200
process đã thoát

INFO:     Shutting down
INFO:     127.0.0.1:40440 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [2795]
```

Request đang chạy vẫn hoàn thành với 200 **sau** khi uvicorn đã nhận SIGTERM (`Shutting down`), rồi lifespan chạy phần dọn dẹp và process tự thoát. Uvicorn ngừng nhận kết nối mới, chờ request đang xử lý xong mới tắt.

### Exercise 5.3: Stateless design

State hội thoại lưu trong **Redis** (`session:<id>`, có TTL) thay vì dict trong RAM. Lý do: khi scale ra nhiều instance, mỗi instance có bộ nhớ riêng — request 1 vào instance A lưu history trong RAM của A, request 2 được LB gửi sang B thì B không thấy gì; instance bị restart/scale down cũng mất sạch. Đưa state ra Redis thì instance nào cũng phục vụ được bất kỳ request nào.

### Exercise 5.4: Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)

```text
NAME                       STATUS                            PORTS
k5-day14-scaling-agent-1   Up 2 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-2   Up 2 seconds (health: starting)   8000/tcp
k5-day14-scaling-agent-3   Up 2 seconds (health: starting)   8000/tcp
k5-day14-scaling-nginx-1   Up 2 seconds                      0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 13 seconds (healthy)           6379/tcp
```

10 request `/health` qua Nginx (cổng 8080) được chia gần đều cho 3 instance:

```text
      3 instance-8279a5
      3 instance-d77cd4
      4 instance-d7952a
```

### Exercise 5.5: Test stateless (`python test_stateless.py`)

```text
Request 1: [instance-8279a5]  Q: What is Docker?
Request 2: [instance-d77cd4]  Q: Why do we need containers?
Request 3: [instance-d7952a]  Q: What is Kubernetes?
Request 4: [instance-8279a5]  Q: How does load balancing work?
Request 5: [instance-d77cd4]  Q: What is Redis used for?
Instances used: {'instance-d77cd4', 'instance-d7952a', 'instance-8279a5'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu trong cùng một session lần lượt rơi vào cả 3 instance (Nginx round-robin), nhưng history vẫn đủ 10 tin nhắn (5 user + 5 assistant) vì mọi instance đọc/ghi cùng key trong Redis.

Thử thêm: tạo session mới rồi `docker stop k5-day14-scaling-agent-1`, đọc lại history 3 lần → cả 3 lần đều `count: 2`, được agent-2 và agent-3 phục vụ (log agent-1: `Instance instance-d77cd4 shutting down`). Một instance chết không làm mất state của người dùng.

## Part 6: Final Project — kết quả `check_production_ready.py`

Chạy đầy đủ (có Docker) trong `06-lab-complete/`, Ubuntu WSL2, Python 3.11, Docker 29.9.3:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 43/43 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

Chi tiết đáng chú ý từ output: image 238 MB (build 40s); 429 sau 5 request thành công với `RATE_LIMIT_PER_MINUTE=5`, restart agent vẫn 429 (state trong Redis); Redis mất kết nối → `/ready` 503, `/health` 200; budget ≈ 0 → 402; SIGTERM khi đang có request → request vẫn 200, exit code 0; `docker stop` → exit code 0 trong 0.8s.

## AI log

| # | Hỏi AI (Claude Code) | Nhận được / dùng gì | Tự sửa & kiểm tra |
|---|---|---|---|
| 1 | Đọc toàn bộ đề, đối chiếu file hướng dẫn tự viết với README/RUBRIC | Danh sách điểm thiếu (Exercise 7.4, `MOCK_ERROR_RATE=0` khi eval, tên ảnh…) | Đối chiếu lại với `README.md`, `RUBRIC.md`, `INSTRUCTOR_GUIDE.md` |
| 2 | Viết code Part 6 theo hợp đồng trong `06-lab-complete/README.md` | `config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py` (sliding window sorted set), `cost_guard.py` (INCRBYFLOAT theo ngày), `main.py` (log JSON, lifespan, xử lý lỗi Redis → 503), Dockerfile multi-stage, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` | TODO: tự ghi phần đã đọc hiểu / chỉnh sửa. Kiểm tra bằng `check_production_ready.py` → PASS 12/12 |
| 3 | Cài Docker Desktop + WSL2 để chạy script chấm đầy đủ | Hướng dẫn `wsl --install -d Ubuntu`, winget Docker, bật WSL integration, venv Python 3.11 bằng `uv` | Tự chạy các lệnh cài đặt; `docker version` thấy Server |
| 4 | Deploy Part 6 lên Render, viết `DEPLOYMENT.md` và Part 3 | Sửa `render.yaml` (thêm `dockerContext`), chỉ ra phải push code + điền Blueprint Path; chạy 4 lệnh CP6; so sánh `railway.toml`/`render.yaml`, tóm tắt pipeline Cloud Run | Tự tạo Blueprint, nhập `AGENT_API_KEY` trên Render; kết quả 200/200/401/200 |
| 6 | Part 7: load test, eval, sửa knowledge base, stack observability | AI chạy `load_test.py`/`run_eval.py`, thêm 2 entry `KNOWLEDGE_BASE` (jwt, hpa) → 23/23; phát hiện và sửa lỗi `PYTHONUSERBASE` trong `production/Dockerfile` (agent crash "No module named uvicorn", lượt benchmark đầu 100% 502 bị bỏ, chạy lại); chạy thí nghiệm alert, đo thời gian firing qua Prometheus API; lấy trace qua Jaeger API v3; soạn `BENCHMARK_REPORT.md` | Tự chụp 4 ảnh Grafana/Jaeger/Prometheus; TODO: tự đối chiếu số trong report với JSON/CSV |
| 5 | Chạy Part 1, 2, 4, 5 và ghi câu trả lời | AI chạy các lệnh trong WSL/Docker, lấy output thật (kích thước image, mã HTTP, log shutdown, test_stateless) và soạn câu trả lời từ code + output | TODO: tự đọc lại từng câu, đối chiếu với code trong từng thư mục |
