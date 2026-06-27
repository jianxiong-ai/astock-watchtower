from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from app.models import Trade
from app.schemas import PositionOut
from app.services.market_data import fetch_sina_quotes
from app.services.symbols import normalize_symbol


@dataclass
class PositionAccumulator:
    symbol: str
    shares: int = 0
    cost_basis: float = 0.0
    realized_pnl: float = 0.0
    total_buy_amount: float = 0.0
    total_sell_amount: float = 0.0
    total_fees: float = 0.0
    warnings: List[str] = field(default_factory=list)

    @property
    def average_cost(self) -> float:
        if self.shares <= 0:
            return 0.0
        return self.cost_basis / self.shares

    def apply_trade(self, trade: Trade) -> None:
        gross = float(trade.price) * int(trade.quantity)
        fee = float(trade.fee or 0)
        self.total_fees += fee

        if trade.side == "buy":
            self.shares += int(trade.quantity)
            self.cost_basis += gross + fee
            self.total_buy_amount += gross + fee
            return

        if trade.side == "sell":
            quantity = int(trade.quantity)
            proceeds = gross - fee
            self.total_sell_amount += proceeds

            if quantity > self.shares:
                self.warnings.append(
                    f"卖出数量 {quantity} 超过卖出前持仓 {self.shares}，请检查交易记录；本次按已有持仓成本结转。"
                )

            matched_quantity = min(quantity, max(self.shares, 0))
            cost_released = self.average_cost * matched_quantity if matched_quantity else 0.0
            self.realized_pnl += proceeds - cost_released
            self.cost_basis -= cost_released
            self.shares -= quantity
            if self.shares <= 0:
                self.cost_basis = 0.0
            return

        self.warnings.append(f"未知交易方向：{trade.side}")


def group_trades(trades: Iterable[Trade]) -> Dict[str, List[Trade]]:
    grouped: Dict[str, List[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.symbol].append(trade)
    for symbol in grouped:
        grouped[symbol].sort(key=lambda item: (item.trade_date, item.id))
    return grouped


async def calculate_positions(
    trades: Iterable[Trade],
    symbol: Optional[str] = None,
    price_overrides: Optional[Dict[str, Dict[str, object]]] = None,
) -> List[PositionOut]:
    grouped = group_trades(trades)
    if symbol:
        normalized = normalize_symbol(symbol)
        grouped = {normalized.symbol: grouped.get(normalized.symbol, [])}

    normalized_symbols = []
    for item in grouped.keys():
        try:
            normalized_symbols.append(normalize_symbol(item))
        except ValueError:
            continue

    quote_warning = ""
    try:
        quotes = await fetch_sina_quotes(normalized_symbols) if normalized_symbols else {}
    except Exception as exc:
        quotes = {}
        quote_warning = f"最新行情读取失败：{exc}"
    positions: List[PositionOut] = []
    for item_symbol, symbol_trades in sorted(grouped.items()):
        accumulator = PositionAccumulator(symbol=item_symbol)
        for trade in symbol_trades:
            accumulator.apply_trade(trade)

        quote = quotes.get(item_symbol, {})
        override = (price_overrides or {}).get(item_symbol) or {}
        latest_price = override.get("price", quote.get("current"))
        latest_price_time = override.get("timestamp", quote.get("timestamp"))
        latest_price_source = override.get("source", quote.get("source"))
        market_value = None
        unrealized_pnl = None
        unrealized_pnl_pct = None
        total_pnl = None
        if isinstance(latest_price, (int, float)) and accumulator.shares != 0:
            market_value = float(latest_price) * accumulator.shares
            unrealized_pnl = market_value - accumulator.cost_basis
            unrealized_pnl_pct = (unrealized_pnl / accumulator.cost_basis * 100) if accumulator.cost_basis else None
            total_pnl = accumulator.realized_pnl + unrealized_pnl
        elif isinstance(latest_price, (int, float)):
            total_pnl = accumulator.realized_pnl

        warnings = list(accumulator.warnings)
        if quote_warning:
            warnings.append(quote_warning)

        positions.append(
            PositionOut(
                symbol=item_symbol,
                shares=accumulator.shares,
                average_cost=round(accumulator.average_cost, 4),
                cost_basis=round(accumulator.cost_basis, 2),
                realized_pnl=round(accumulator.realized_pnl, 2),
                total_buy_amount=round(accumulator.total_buy_amount, 2),
                total_sell_amount=round(accumulator.total_sell_amount, 2),
                total_fees=round(accumulator.total_fees, 2),
                latest_price=round(float(latest_price), 4) if isinstance(latest_price, (int, float)) else None,
                latest_price_time=str(latest_price_time or "") or None,
                market_value=round(market_value, 2) if market_value is not None else None,
                unrealized_pnl=round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                unrealized_pnl_pct=round(unrealized_pnl_pct, 2) if unrealized_pnl_pct is not None else None,
                total_pnl=round(total_pnl, 2) if total_pnl is not None else None,
                source=str(latest_price_source or "Sina secondary quote"),
                warnings=warnings,
            )
        )
    return positions
