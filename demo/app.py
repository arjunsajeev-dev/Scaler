import time

from fastapi import FastAPI

app = FastAPI(title="scaler-demo")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/burn")
def burn(seconds: float = 0.5) -> dict[str, int | float]:
    """Busy-loop so the orchestrator can observe CPU pressure."""
    seconds = min(max(seconds, 0.0), 10.0)
    end = time.perf_counter() + seconds
    n = 0
    while time.perf_counter() < end:
        n += 1
    return {"seconds": seconds, "iters": n}
