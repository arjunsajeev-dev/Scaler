"""Hysteresis + cooldown scaling decisions. Engine state lives in Redis."""

from __future__ import annotations

from app.config import ServicePolicy
from app.models import EngineState, ScaleDecision


def evaluate(
    avg_cpu: float | None,
    actual: int,
    desired: int,
    policy: ServicePolicy,
    state: EngineState,
    now: float,
) -> tuple[ScaleDecision, EngineState]:
    """Return a (possibly no-op) decision and the updated engine state.

    Scale-up requires `scale_up_ticks` consecutive ticks above the high
    threshold. Scale-down requires `scale_down_ticks` consecutive ticks
    below the low threshold. Opposite-signal ticks reset the other counter.
    Cooldown is measured from `last_scale_at`.
    """
    state = state.model_copy()
    if avg_cpu is None:
        return (
            ScaleDecision(direction=None, desired=desired, reason="no metrics yet"),
            state,
        )

    high = avg_cpu > policy.scale_up_cpu
    low = avg_cpu < policy.scale_down_cpu

    if high:
        state.consecutive_high += 1
        state.consecutive_low = 0
    elif low:
        state.consecutive_low += 1
        state.consecutive_high = 0
    else:
        state.consecutive_high = 0
        state.consecutive_low = 0

    cooldown_ok = (
        state.last_scale_at is None
        or (now - state.last_scale_at) >= policy.cooldown_seconds
    )

    if (
        high
        and state.consecutive_high >= policy.scale_up_ticks
        and cooldown_ok
        and desired < policy.max_replicas
    ):
        new_desired = min(desired + 1, policy.max_replicas)
        state.last_scale_at = now
        state.consecutive_high = 0
        return (
            ScaleDecision(
                direction="up",
                desired=new_desired,
                reason=(
                    f"avg_cpu {avg_cpu:.1f}% > {policy.scale_up_cpu}% "
                    f"for {policy.scale_up_ticks} ticks"
                ),
            ),
            state,
        )

    if (
        low
        and state.consecutive_low >= policy.scale_down_ticks
        and cooldown_ok
        and desired > policy.min_replicas
    ):
        new_desired = max(desired - 1, policy.min_replicas)
        state.last_scale_at = now
        state.consecutive_low = 0
        return (
            ScaleDecision(
                direction="down",
                desired=new_desired,
                reason=(
                    f"avg_cpu {avg_cpu:.1f}% < {policy.scale_down_cpu}% "
                    f"for {policy.scale_down_ticks} ticks"
                ),
            ),
            state,
        )

    if high and desired >= policy.max_replicas:
        reason = "at max replicas"
    elif low and desired <= policy.min_replicas:
        reason = "at min replicas"
    elif (high or low) and not cooldown_ok:
        remaining = policy.cooldown_seconds - (now - (state.last_scale_at or now))
        reason = f"cooldown ({remaining:.1f}s remaining)"
    elif high:
        reason = (
            f"high cpu {avg_cpu:.1f}% "
            f"({state.consecutive_high}/{policy.scale_up_ticks} ticks)"
        )
    elif low:
        reason = (
            f"low cpu {avg_cpu:.1f}% "
            f"({state.consecutive_low}/{policy.scale_down_ticks} ticks)"
        )
    else:
        reason = f"cpu {avg_cpu:.1f}% within band"

    return ScaleDecision(direction=None, desired=desired, reason=reason), state
