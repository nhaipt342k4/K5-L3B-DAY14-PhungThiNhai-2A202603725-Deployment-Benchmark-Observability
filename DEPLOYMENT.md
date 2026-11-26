# Deployment Information

## Public URL

https://day14-agent-8wjd.onrender.com

## Platform

**Render** (Blueprint từ [`06-lab-complete/render.yaml`](06-lab-complete/render.yaml)), Docker runtime, gói free.

| Tài nguyên Render | Loại | Vai trò |
|---|---|---|
| `day14-agent` | Web Service (Docker) | Agent Part 6, build từ `06-lab-complete/Dockerfile`, health check `/health` |
| `day14-redis` | Key Value (Redis) | State dùng chung cho rate limit và cost guard |

> Gói free của Render cho service ngủ sau một thời gian không có request; request đầu tiên sau khi ngủ có thể mất 30–60 giây.

## Test Commands

Đặt `BASE` là URL public và `AGENT_API_KEY` là key đã nhập trên Render (không ghi giá trị vào repo). Mỗi lệnh chỉ in mã HTTP.

```bash
BASE=https://day14-agent-8wjd.onrender.com

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả đã chạy (2026-11-26): `200`, `200`, `401`, `200`.

- `GET /ready` → `{"status":"ready","redis":"ok"}` (agent kết nối được Key Value Redis trên Render).
- `POST /ask` có key → `{"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{...}}`.
- `python check_production_ready.py --public-url https://day14-agent-8wjd.onrender.com` → `✅ Public URL: GET /health → 200`.

## Environment Variables Set

Đặt trên Render (qua Blueprint), không ghi giá trị secret trong code:

| Biến | Nguồn |
|---|---|
| `AGENT_API_KEY` | Secret, `sync: false` — nhập tay trên dashboard Render |
| `REDIS_URL` | `fromService` → `connectionString` của Key Value `day14-redis` |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `PORT` | Render tự cấp; Dockerfile `CMD` đọc `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
