"""Hysteresis and cooldown behaviour of the scaling engine."""

from __future__ import annotations

from app.config import ServicePolicy
from app.core.engine import evaluate
from app.models import EngineState


def _policy(**overrides) -> ServicePolicy:
    data = dict(
        name="demo",
        image="scaler-demo:latest",
        min_replicas=1,
        max_replicas=5,
        scale_up_cpu=80,
        scale_down_cpu=30,
        scale_up_ticks=3,
        scale_down_ticks=5,
        cooldown_seconds=30,
    )
    data.update(overrides)
    return ServicePolicy(**data)


def test_three_high_ticks_scale_up():
    policy = _policy()
    state = EngineState()
    desired = 1
    for i, cpu in enumerate((81, 85, 90), start=1):
        decision, state = evaluate(cpu, 1, desired, policy, state, now=1_000.0 + i)
        if i < 3:
            assert decision.direction is None
        else:
            assert decision.direction == "up"
            assert decision.desired == 2


def test_two_high_ticks_do_not_scale():
    policy = _policy()
    state = EngineState()
    decision, state = evaluate(90, 1, 1, policy, state, now=1.0)
    decision, state = evaluate(90, 1, 1, policy, state, now=2.0)
    assert decision.direction is None
    assert state.consecutive_high == 2


def test_opposite_signal_resets_counters():
    policy = _policy()
    state = EngineState()
    evaluate(90, 1, 1, policy, state, now=1.0)
    evaluate(90, 1, 1, policy, state, now=2.0)
    decision, state = evaluate(10, 1, 1, policy, state, now=3.0)
    assert decision.direction is None
    assert state.consecutive_high == 0
    assert state.consecutive_low == 1


def test_five_low_ticks_scale_down():
    policy = _policy()
    state = EngineState()
    desired = 3
    for i in range(1, 6):
        decision, state = evaluate(10, 3, desired, policy, state, now=float(i))
        if i < 5:
            assert decision.direction is None
        else:
            assert decision.direction == "down"
            assert decision.desired == 2


def test_cooldown_blocks_immediate_reverse():
    policy = _policy(cooldown_seconds=30)
    state = EngineState()
    desired = 1
    now = 1_000.0
    for i in range(3):
        decision, state = evaluate(90, 1, desired, policy, state, now=now + i)
    assert decision.direction == "up"
    desired = decision.desired
    # Immediate low ticks during cooldown must not scale down.
    for i in range(5):
        decision, state = evaluate(10, 2, desired, policy, state, now=now + 3 + i)
        assert decision.direction is None
    # Counters persist through cooldown, so the first eligible tick scales down.
    later = now + 3 + 5 + 30
    decision, state = evaluate(10, 2, desired, policy, state, now=later)
    assert decision.direction == "down"
    assert decision.desired == 1


def test_respects_max_replicas():
    policy = _policy(max_replicas=2)
    state = EngineState()
    for i in range(3):
        decision, state = evaluate(90, 2, 2, policy, state, now=float(i))
    assert decision.direction is None
    assert decision.desired == 2


def test_respects_min_replicas():
    policy = _policy(min_replicas=1)
    state = EngineState()
    for i in range(5):
        decision, state = evaluate(5, 1, 1, policy, state, now=float(i))
    assert decision.direction is None
    assert decision.desired == 1


def test_no_metrics_is_noop():
    policy = _policy()
    decision, state = evaluate(None, 1, 1, policy, EngineState(), now=1.0)
    assert decision.direction is None
    assert "no metrics" in decision.reason
