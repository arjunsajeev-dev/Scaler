from pathlib import Path

from fakeredis import FakeAsyncRedis

from app.config import ServicePolicy, load_services_file
from app.core.policies import build_policy, load_live_policies
from app.store.redis_store import RedisStore


def test_services_yml_includes_demo_alpha_beta():
    path = Path(__file__).resolve().parent.parent / "config" / "services.yml"
    _, policies = load_services_file(path)
    assert set(policies) == {"demo", "alpha", "beta"}
    assert policies["demo"].image == "scaler-demo:latest"
    assert policies["alpha"].image == "scaler-alpha:latest"
    assert policies["beta"].image == "scaler-beta:latest"
    assert policies["alpha"].traefik.rule == "PathPrefix(`/alpha`)"
    assert policies["beta"].traefik.rule == "PathPrefix(`/beta`)"
    assert policies["beta"].container_port == 80
    assert policies["demo"].traefik.rule != policies["alpha"].traefik.rule
    assert policies["alpha"].traefik.rule != policies["beta"].traefik.rule


def test_build_policy_defaults_traefik_from_name():
    policy = build_policy("gamma", "scaler-gamma:latest")
    assert policy.traefik.rule == "PathPrefix(`/gamma`)"
    assert policy.traefik.strip_prefix == "/gamma"


async def test_live_policies_merge_redis_overlay():
    path = Path(__file__).resolve().parent.parent / "config" / "services.yml"
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisStore(redis)
    await store.upsert_dynamic_policy(
        ServicePolicy(name="gamma", image="scaler-gamma:latest")
    )
    policies, registry = await load_live_policies(path, store)
    assert set(policies) >= {"demo", "alpha", "beta", "gamma"}
    assert registry.is_file_backed("demo")
    assert registry.is_dynamic("gamma")
    await redis.aclose()
