"""
Production AI Agent — Part 6 Final Project

Chạy:   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
Kiểm:   python check_production_ready.py
"""
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        # Các field thêm qua logger.info("...", extra={"fields": {...}})
        entry.update(getattr(record, "fields", {}) or {})
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(entry, ensure_ascii=False, default=str)


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("agent")
    log.setLevel(settings.log_level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.handlers = [handler]
    log.propagate = False      # không đi qua handler mặc định (không phải JSON)
    return log


logger = _setup_logger()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


# ─────────────────────────────────────────────────────────
# Lifespan + graceful shutdown (tiêu chí 11)
#   uvicorn tự bắt SIGTERM: ngừng nhận kết nối mới, chờ request đang chạy xong,
#   rồi chạy phần sau `yield` và thoát với exit code 0. Không tự đăng ký signal
#   handler để không ghi đè handler của uvicorn.
# ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event("startup", environment=settings.environment,
              rate_limit_per_minute=settings.rate_limit_per_minute,
              daily_budget_usd=settings.daily_budget_usd,
              redis_ok=redis_healthy())
    yield
    log_event("shutdown", reason="SIGTERM or stop — in-flight requests completed")
    try:
        r.close()
    except Exception:
        pass


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


# ─────────────────────────────────────────────────────────
# Middleware: log mỗi request + request id
# ─────────────────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log_event("request", logging.ERROR, request_id=request_id, method=request.method,
                  path=request.url.path, status=500,
                  ms=round((time.perf_counter() - start) * 1000, 1))
        raise
    response.headers["X-Request-ID"] = request_id
    log_event("request", request_id=request_id, method=request.method,
              path=request.url.path, status=response.status_code,
              ms=round((time.perf_counter() - start) * 1000, 1))
    return response


# ─────────────────────────────────────────────────────────
# Xử lý lỗi: trả JSON rõ ràng, không lộ stack trace
# ─────────────────────────────────────────────────────────
@app.exception_handler(RedisError)
async def redis_error_handler(request: Request, exc: RedisError):
    log_event("redis_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log_event("unhandled_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): process còn chạy là 200, không phụ thuộc Redis."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): chỉ 200 khi Redis kết nối được, ngược lại 503."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "unreachable"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)      # 429 khi vượt RATE_LIMIT_PER_MINUTE
    check_budget()                 # 402 khi hết DAILY_BUDGET_USD

    answer = llm_ask(body.question)

    input_tokens = estimate_tokens(body.question)
    output_tokens = estimate_tokens(answer)
    cost = record_cost(input_tokens, output_tokens)
    log_event("llm_call", input_tokens=input_tokens, output_tokens=output_tokens,
              cost_usd=round(cost, 8), q_len=len(body.question))

    return {
        "question": body.question,
        "answer": answer,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "cost_usd": round(cost, 8)},
    }
