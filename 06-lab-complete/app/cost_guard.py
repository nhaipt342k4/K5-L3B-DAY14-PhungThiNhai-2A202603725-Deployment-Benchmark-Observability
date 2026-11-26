"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày (UTC)
  • Tổng chi phí trong ngày đã đạt DAILY_BUDGET_USD → HTTP 402
  • Key tự hết hạn sau 2 ngày → budget tự reset mỗi ngày
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

KEY_TTL_SECONDS = 2 * 24 * 3600


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc):%Y-%m-%d}"


def estimate_tokens(text: str) -> int:
    """Mock LLM không trả usage → ước lượng ~4 ký tự / token."""
    return max(1, len(text) // 4)


def current_spend() -> float:
    return float(r.get(_daily_key()) or 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → 402 Payment Required."""
    spent = current_spend()
    if spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=f"Daily budget exhausted (${spent:.6f} / ${settings.daily_budget_usd:.6f})",
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng ngày, trả về chi phí request."""
    cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K
    key = _daily_key()
    pipe = r.pipeline()
    pipe.incrbyfloat(key, cost)
    pipe.expire(key, KEY_TTL_SECONDS)
    pipe.execute()
    return cost
