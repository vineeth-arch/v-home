"""RAM-only worker status: last Brain snapshot and worker heartbeat. Lost on restart by design (never hits the SD)."""
from . import contracts

HOUSEKEEPING = ("expire_leases", "purge")


class StatusHolder:
    def __init__(self, clock):
        self.clock = clock
        self.snapshot, self.snapshot_mono = None, None
        self.worker_mono, self.worker, self.version = None, "", ""
        self.runs = {n: dict(run=None, err=None, err_type=None) for n in HOUSEKEEPING}

    def record(self, name, err=None):
        """Housekeeping task finished (err=None) or failed. Monotonic stamps: wall time lies before NTP sync."""
        r = self.runs.setdefault(name, dict(run=None, err=None, err_type=None))
        r["run"] = self.clock.mono()
        if err is not None:
            r["err"], r["err_type"] = r["run"], type(err).__name__

    def housekeeping(self):
        return {n: {"last_run_age_s": self._age(r["run"]), "last_error_age_s": self._age(r["err"]),
                    "last_error": r["err_type"]} for n, r in self.runs.items()}

    def set_snapshot(self, obj):
        self.snapshot, self.snapshot_mono = obj, self.clock.mono()

    def heartbeat(self, worker, version):
        self.worker_mono, self.worker, self.version = self.clock.mono(), str(worker)[:40], str(version)[:40]

    def _age(self, mono):
        return None if mono is None else max(0, int(self.clock.mono() - mono))

    def brain_status(self, counts):
        snap_age, seen_age = self._age(self.snapshot_mono), self._age(self.worker_mono)
        return {"snapshot": self.snapshot, "snapshot_age_s": snap_age,
                "stale": snap_age is None or snap_age > contracts.SNAPSHOT_STALE_S,
                "worker_last_seen_age_s": seen_age,
                "worker_stale": seen_age is None or seen_age > contracts.WORKER_STALE_S,
                "queue": counts}
