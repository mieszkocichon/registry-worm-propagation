# ADR-0015: Hard Wall-Clock Timeout via Per-Call Daemon Watchdog Threads

## Status
Accepted

## Context
`requests.get(url, timeout=N)` bounds *per-socket-read* latency, not total
call duration. Under bursty concurrent load, ecosyste.ms was observed to
hold connections open and trickle data slowly rather than rejecting cleanly
with `429` — a request can sit just under the read-timeout on every
individual `recv()` while never completing, hanging effectively forever.

The first fix routed all HTTP calls through a shared
`concurrent.futures.ThreadPoolExecutor`, with a hard wall-clock deadline
enforced via `future.result(timeout=hard_timeout)`. This masked the symptom
but introduced a worse failure mode: `ThreadPoolExecutor` worker threads are
**non-daemon** by default. If a submitted task's underlying
`requests.get()` call genuinely hung (rather than merely being slow), the
worker thread executing it never returned — and because non-daemon threads
block interpreter shutdown, the entire Python process stayed alive
indefinitely even after all application logic (including the final "Saved
... to path" print) had completed. This produced invisible zombie
`python.exe` processes that kept running and kept writing to the shared
output JSONL file. Three such zombies were found racing on
`pypi_maintainers.jsonl` simultaneously, causing a target overshoot (14,588
vs. a 12,000 target) and 8 duplicate lines.

## Decision
Replace the shared `ThreadPoolExecutor` watchdog with a **per-call daemon
thread**:

```python
def http_get(url, timeout=10, hard_timeout=15, **kwargs):
    box = {}
    def worker():
        try:
            box['response'] = requests.get(url, timeout=timeout, **kwargs)
        except Exception as e:
            box['error'] = e
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(hard_timeout)
    if t.is_alive():
        raise requests.exceptions.Timeout(f"hard timeout ({hard_timeout}s) exceeded for {url}")
    if 'error' in box:
        raise box['error']
    return box['response']
```

`daemon=True` is the load-bearing detail: a thread stuck on a dead socket
can never block process exit, regardless of how the call site handles the
timeout exception.

## Consequences

### Positive
* No more zombie processes — a genuinely-hung request is bounded at
  `hard_timeout` seconds and cleanly abandoned instead of stalling the
  entire interpreter.
* Process exit is now guaranteed independent of network conditions,
  restoring safe `Get-Process python` / background-task status checks as a
  reliable signal.
* Eliminates the concurrent-write race that produced duplicate/overshoot
  data in output JSONL files.

### Negative
* An abandoned request's OS-level socket is not force-closed, only
  detached from the joining thread — it lingers until garbage collection
  or OS-level cleanup. A bounded resource leak under repeated hangs;
  acceptable at this project's request volume (thousands, not millions, of
  calls per run).
