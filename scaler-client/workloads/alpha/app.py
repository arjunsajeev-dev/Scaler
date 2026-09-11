import time

from fastapi import FastAPI

app = FastAPI(title="scaler-alpha")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "alpha"}


@app.get("/whoami")
def whoami() -> dict[str, str]:
    return {"service": "alpha", "image": "scaler-alpha:latest"}


@app.get("/burn")
def burn(seconds: float = 0.5) -> dict[str, int | float | str]:
    """Busy-loop so the orchestrator can observe CPU pressure."""
    seconds = min(max(seconds, 0.0), 10.0)
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end:
        n += 1
    return {"service": "alpha", "seconds": seconds, "iters": n}
