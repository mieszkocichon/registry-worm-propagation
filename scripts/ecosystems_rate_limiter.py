import threading
import time

class RateLimiter:
    """
    Thread-safe global pacer: blocks callers until at least `min_interval`
    seconds have passed since the last permitted call. Used to spread
    concurrent worker requests out in time instead of firing them all at
    once, since ecosyste.ms appears to stall/hold connections under bursty
    concurrent load rather than cleanly rejecting with 429.
    """
    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.last_call = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_call
            sleep_for = self.min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self.last_call = time.monotonic()

# Shared pacer, per process: ~1.4 req/sec, regardless of how many worker
# threads call it. Combined with the existing reactive 429 backoff, this
# keeps request starts spread out in time instead of arriving in a burst —
# bursty concurrent arrival is what seemed to make ecosyste.ms stall/hold
# connections instead of cleanly returning 429. Note: this limiter is
# per-process — if the maintainers and dependents backfill scripts run
# simultaneously, combined load is roughly double this rate.
ecosystems_limiter = RateLimiter(min_interval=0.7)
