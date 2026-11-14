"""List NISAR GCOV dual-pol granules over Indonesian Borneo from CMR and write data/inventory.json."""
import json
import re
import urllib.request
from pathlib import Path

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
SHORT_NAME = "NISAR_L2_GCOV_PROVISIONAL_V1"
BBOX = "108.5,-4.3,119.3,4.4"
TEMPORAL = "2026-06-01T00:00:00Z,2026-11-14T00:00:00Z"
BROWSE_ROOT = "https://nisar.asf.earthdatacloud.nasa.gov/BROWSE/" + SHORT_NAME
TITLE_RE = re.compile(
    r"NISAR_L2_PR_GCOV_(?P<cycle>\d{3})_(?P<track>\d{3})_(?P<dir>[AD])_(?P<frame>\d{3})_"
    r"(?P<mode>\d{4})_(?P<pol>[A-Z]{4})_[A-Z]_(?P<start>\d{8}T\d{6})_\d{8}T\d{6}_"
    r"(?P<crid>[A-Z0-9]+)_[A-Z]_[A-Z]_[A-Z]_(?P<rev>\d{3})$"
)
OUT = Path(__file__).parent / "data" / "inventory.json"


def fetch_entries() -> list[dict]:
    """Page through CMR with search-after and return every entry."""
    entries, after = [], None
    while True:
        req = urllib.request.Request(
            f"{CMR}?short_name={SHORT_NAME}&bounding_box={BBOX}&temporal={TEMPORAL}&page_size=2000"
        )
        if after:
            req.add_header("CMR-Search-After", after)
        with urllib.request.urlopen(req, timeout=120) as resp:
            page = json.load(resp)["feed"]["entry"]
            after = resp.headers.get("CMR-Search-After")
        entries += page
        if len(page) < 2000 or not after:
            return entries


def parse(entry: dict) -> dict | None:
    """Turn a CMR entry into an inventory record, or None if the title does not parse."""
    m = TITLE_RE.match(entry["title"])
    if not m:
        return None
    nums = list(map(float, entry["polygons"][0][0].split()))
    lat, lon = nums[0::2][:-1], nums[1::2][:-1]
    title = entry["title"]
    return {
        "title": title,
        "key": title.rsplit("_", 1)[0],
        "rev": int(m["rev"]),
        "tf": f"{m['track']}{m['dir']}_{m['frame']}",
        "pol": m["pol"],
        "date": m["start"][:8],
        "lat": lat,
        "lon": lon,
        "browse": f"{BROWSE_ROOT}/{title}/{title}",
    }


def main() -> None:
    """Query, deduplicate reprocessings (keep the highest revision) and keep dual-pol HH+HV."""
    recs = [r for r in map(parse, fetch_entries()) if r]
    latest: dict[str, dict] = {}
    for r in recs:
        if r["key"] not in latest or r["rev"] > latest[r["key"]]["rev"]:
            latest[r["key"]] = r
    keep = sorted((r for r in latest.values() if r["pol"] == "DHDH"), key=lambda r: (r["tf"], r["date"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(keep, indent=1))
    print(f"{len(recs)} entries, {len(latest)} unique, {len(keep)} dual-pol HH+HV, "
          f"{len({r['tf'] for r in keep})} track-frames -> {OUT}")


if __name__ == "__main__":
    main()
