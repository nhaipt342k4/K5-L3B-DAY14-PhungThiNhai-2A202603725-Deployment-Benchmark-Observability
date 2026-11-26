# Day 14 Lab — Mission Answers

## Part 1: Localhost vs Production

> TODO (CP1)

## Part 2: Docker

> TODO (CP2)

## Part 3: Cloud Deployment

> TODO (CP6) — URL public, so sánh `railway.toml` / `render.yaml`, pipeline Cloud Run (Exercise 3.3)

## Part 4: API Security

> TODO (CP3)

## Part 5: Scaling & Reliability

> TODO (CP4)

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
