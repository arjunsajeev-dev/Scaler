from pathlib import Path

from app.config import load_services_file


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
