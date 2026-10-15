from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from app.market.types import CandleBar, CandleFeatures

ZERO = Decimal(0)
ONE = Decimal(1)


def _ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result
    with localcontext() as context:
        context.prec = 60
        current = sum(values[:period], ZERO) / Decimal(period)
        result[period - 1] = current
        multiplier = Decimal(2) / Decimal(period + 1)
        for index in range(period, len(values)):
            current = (values[index] - current) * multiplier + current
            result[index] = current
    return result


def _rsi(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) <= period:
        return result
    with localcontext() as context:
        context.prec = 60
        gains: list[Decimal] = []
        losses: list[Decimal] = []
        for previous, current in zip(values, values[1:], strict=False):
            change = current - previous
            gains.append(max(change, ZERO))
            losses.append(max(-change, ZERO))
        average_gain = sum(gains[:period], ZERO) / Decimal(period)
        average_loss = sum(losses[:period], ZERO) / Decimal(period)
        result[period] = _rsi_value(average_gain, average_loss)
        for index in range(period + 1, len(values)):
            average_gain = (average_gain * Decimal(period - 1) + gains[index - 1]) / Decimal(period)
            average_loss = (average_loss * Decimal(period - 1) + losses[index - 1]) / Decimal(
                period
            )
            result[index] = _rsi_value(average_gain, average_loss)
    return result


def _rsi_value(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_loss == ZERO:
        return Decimal(100) if average_gain > ZERO else Decimal(50)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (ONE + relative_strength)


def calculate_features(candles: Sequence[CandleBar]) -> tuple[CandleFeatures, ...]:
    """Calculate EMA(20), Wilder RSI(7), and MACD(12,26,9) oldest to newest.

    EMA values start with an SMA seed. RSI uses Wilder smoothing and becomes
    available after seven price changes. MACD and its signal stay null until
    their full warmup windows are available.
    """
    bars = tuple(candles)
    for left, right in zip(bars, bars[1:], strict=False):
        if left.symbol != right.symbol or left.interval != right.interval:
            raise ValueError("indicator input must contain one symbol and interval")
        if left.open_at >= right.open_at:
            raise ValueError("candles must be ordered oldest to newest without duplicates")
    closes = [bar.close for bar in bars]
    ema20 = _ema(closes, 20)
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    rsi7 = _rsi(closes, 7)
    macd_values: list[Decimal | None] = [
        fast - slow if fast is not None and slow is not None else None
        for fast, slow in zip(ema12, ema26, strict=True)
    ]
    available_macd = [value for value in macd_values if value is not None]
    macd_signal_available = _ema(available_macd, 9)
    signal_by_index: list[Decimal | None] = [None] * len(bars)
    macd_offset = next(
        (index for index, value in enumerate(macd_values) if value is not None), len(bars)
    )
    for offset, signal in enumerate(macd_signal_available):
        signal_by_index[macd_offset + offset] = signal

    histogram: list[Decimal | None] = []
    for macd, signal in zip(macd_values, signal_by_index, strict=True):
        histogram.append(macd - signal if macd is not None and signal is not None else None)

    return tuple(
        CandleFeatures(
            candle=bar,
            ema20=ema20[index],
            rsi7=rsi7[index],
            macd=macd_values[index],
            macd_signal=signal_by_index[index],
            macd_histogram=histogram[index],
        )
        for index, bar in enumerate(bars)
    )
