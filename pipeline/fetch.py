"""Download the public HH and HV browse PNGs for every granule in data/inventory.json."""
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DATA = Path(__file__).parent / "data"
RAW = DATA / "raw"
LAYERS = ("HVHV", "HHHH")


def get(job: tuple[str, Path]) -> str:
    """Fetch one URL to a file unless it is already there; return a status word."""
    url, dest = job
    if dest.exists() and dest.stat().st_size > 0:
        return "cached"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:
            body = resp.read()
    except Exception as exc:  # report and keep going; a missing browse is not fatal
        return f"fail {dest.name}: {exc}"
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(body)
    tmp.rename(dest)
    return "ok"


def main() -> None:
    """Fetch every missing layer with 8 parallel requests."""
    inv = json.loads((DATA / "inventory.json").read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = [(f"{r['browse']}_NATIVE_A_{layer}.png", RAW / f"{r['key']}_{layer}.png")
            for r in inv for layer in LAYERS]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(get, jobs))
    fails = [s for s in results if s.startswith("fail")]
    print(f"{len(jobs)} files: {results.count('ok')} fetched, {results.count('cached')} cached, {len(fails)} failed")
    for f in fails:
        print(f)


if __name__ == "__main__":
    main()
