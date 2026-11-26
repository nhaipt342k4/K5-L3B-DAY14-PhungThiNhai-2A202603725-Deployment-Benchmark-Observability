"""
Rate limiting (tiêu chí 7) — sliding window 60 giây, state trong Redis.

Mỗi API key có 1 sorted set: member = 1 request, score = thời điểm (giây).
  1. ZREMRANGEBYSCORE  xoá request cũ hơn 60s
  2. ZCARD             đếm request còn trong cửa sổ
  3. đủ giới hạn       → 429 + Retry-After (lúc request cũ nhất rời cửa sổ)
  4. ZADD + EXPIRE     ghi nhận request này

Lưu trong Redis (không dùng dict trong RAM) nên mọi worker / instance dùng chung
và state còn nguyên khi restart agent.
"""
import hashlib
import math
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _redis_key(api_key: str) -> str:
    # Băm API key để không lưu secret dạng rõ trong Redis.
    digest = hashlib.sha256(api_key.encode()).hexdigest()[:16]
    return f"ratelimit:{digest}"


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    redis_key = _redis_key(key)
    now = time.time()

    pipe = r.pipeline()
    pipe.zremrangebyscore(redis_key, 0, now - WINDOW_SECONDS)
    pipe.zcard(redis_key)
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(redis_key, 0, 0, withscores=True)
        retry_after = WINDOW_SECONDS
        if oldest:
            retry_after = max(1, math.ceil(oldest[0][1] + WINDOW_SECONDS - now))
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {limit} requests per {WINDOW_SECONDS}s",
            headers={"Retry-After": str(retry_after)},
        )

    pipe = r.pipeline()
    pipe.zadd(redis_key, {f"{now}:{uuid.uuid4().hex}": now})
    pipe.expire(redis_key, WINDOW_SECONDS + 1)
    pipe.execute()
