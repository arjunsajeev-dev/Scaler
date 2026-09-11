from scaler.controller.reconciler import unused_indices
from scaler.docker.templates import render_labels, replica_name
from scaler.config import ServicePolicy, TraefikConfig


def test_unused_indices_fill_holes():
    assert unused_indices({0, 2}, 2) == [1, 3]


def test_unused_indices_from_empty():
    assert unused_indices(set(), 3) == [0, 1, 2]


def test_replica_name():
    assert replica_name("demo", 3) == "orch-demo-3"


def test_traefik_labels_rendered():
    policy = ServicePolicy(
        name="demo",
        image="scaler-demo:latest",
        traefik=TraefikConfig(
            enabled=True, rule="PathPrefix(`/demo`)", strip_prefix="/demo"
        ),
    )
    labels = render_labels(policy, 2)
    assert labels["orchestrator.service"] == "demo"
    assert labels["orchestrator.managed"] == "true"
    assert labels["orchestrator.index"] == "2"
    assert labels["traefik.enable"] == "true"
    assert labels["traefik.http.routers.demo.rule"] == "PathPrefix(`/demo`)"
    assert labels["traefik.http.services.demo.loadbalancer.server.port"] == "8000"
