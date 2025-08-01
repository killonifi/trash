
"""tests.py – quick non‑unit tests for FlybackCore."""

from flyback_core import FlybackCore
import random

def rand_tuples(n, vmin=3, vmax=24, imin=0.1, imax=3):
    return [(random.uniform(vmin, vmax), random.uniform(imin, imax)) for _ in range(n)]

configs = [
    # Vin_min, Vin_max, outputs list ...
    (85, 265, rand_tuples(3)),
    (36, 75, rand_tuples(2)),
    (250, 450, rand_tuples(4)),
    (85, 115, rand_tuples(1)),
    (9, 18, rand_tuples(3)),
    (20, 60, rand_tuples(3)),
    (300, 400, rand_tuples(2)),
    (48, 57, rand_tuples(4)),
    (90, 140, rand_tuples(3)),
    (120, 240, rand_tuples(2)),
]

def run():
    for idx, (vin_min, vin_max, outs) in enumerate(configs, 1):
        V,I = zip(*outs)
        core = FlybackCore(vin_min, vin_max, list(V), list(I))
        res = core()
        print(f"Case {idx}: D={res.D:.2f}, Ipk={res.Ipk:.1f} A, Lp={res.Lp*1e6:.1f} uH, OK")

if __name__ == "__main__":
    run()
