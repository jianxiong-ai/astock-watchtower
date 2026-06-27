import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.models import Trade
from app.services.positions import calculate_positions


def test_calculate_positions_uses_moving_average_cost_and_realized_pnl():
    trades = [
        Trade(id=1, symbol="600519.SH", trade_date=datetime(2026, 1, 1, 10, 0), side="buy", price=100, quantity=100, fee=5),
        Trade(id=2, symbol="600519.SH", trade_date=datetime(2026, 1, 2, 10, 0), side="buy", price=110, quantity=100, fee=5),
        Trade(id=3, symbol="600519.SH", trade_date=datetime(2026, 1, 3, 10, 0), side="sell", price=120, quantity=100, fee=5),
    ]

    quote = {
        "600519.SH": {
            "current": 130.0,
            "timestamp": "2026-06-26T15:00:00+08:00",
            "source": "test quote",
        }
    }
    with patch("app.services.positions.fetch_sina_quotes", AsyncMock(return_value=quote)):
        positions = asyncio.run(calculate_positions(trades))

    assert len(positions) == 1
    position = positions[0]
    assert position.symbol == "600519.SH"
    assert position.shares == 100
    assert position.average_cost == 105.05
    assert position.cost_basis == 10505.0
    assert position.realized_pnl == 1490.0
    assert position.market_value == 13000.0
    assert position.unrealized_pnl == 2495.0
    assert position.total_pnl == 3985.0
