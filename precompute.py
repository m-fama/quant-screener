"""Precompute + save dashboard snapshots so the app loads instantly.

The dashboard reads these committed snapshots in milliseconds instead of
fetching ~1,000+ tickers live on every cold start / redeploy.

Usage:
    python precompute.py                      # the common combos (fast, recommended)
    python precompute.py --all                # full universe x horizon grid
    python precompute.py --only emerging:emerging us_all:mid
"""

from __future__ import annotations

import argparse
import time

import snapshots

# Combos users actually hit (each universe with its sensible horizons).
DEFAULT = [
    ("emerging", "emerging"), ("emerging", "mid"), ("emerging", "value"),
    ("us_all", "mid"), ("us_all", "value"), ("us_all", "long"), ("us_all", "short"),
    ("etfs", "mid"), ("etfs", "short"),
    ("commodities", "short"), ("commodities", "mid"),
    ("ngx", "short"), ("ngx", "mid"),
]

UNIVERSES = ["us_all", "emerging", "etfs", "commodities", "ngx"]
HORIZONS = ["short", "mid", "long", "value", "emerging"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Precompute dashboard snapshots")
    ap.add_argument("--all", action="store_true", help="full universe x horizon grid")
    ap.add_argument("--only", nargs="*", default=None,
                    help="specific 'universe:horizon' pairs")
    args = ap.parse_args()

    if args.only:
        combos = [tuple(x.split(":", 1)) for x in args.only]
    elif args.all:
        combos = [(u, h) for u in UNIVERSES for h in HORIZONS]
    else:
        combos = DEFAULT

    print(f"Precomputing {len(combos)} snapshot(s)...\n")
    ok = 0
    for u, h in combos:
        t0 = time.time()
        try:
            info = snapshots.save(u, h)
            print(f"  OK  {u:12s} {h:9s} {info['rows']:>4d} rows  ({time.time() - t0:.1f}s)")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERR {u:12s} {h:9s} -> {e}")
    print(f"\nDone: {ok}/{len(combos)} snapshots saved to {snapshots.SNAP_DIR}")


if __name__ == "__main__":
    main()
