#!/usr/bin/env python3
"""
metrics.py — audiencia real sin rastreadores de terceros.

La API de releases de GitHub expone `download_count` por cada asset. Como el
MP3 de cada episodio ES un asset de release, ese contador equivale al número
de descargas del episodio: la misma métrica que venden Podtrac o Chartable,
sin prefijos de redirección, sin cookies y sin exponer a los oyentes.

`download_count` es acumulativo y GitHub no guarda histórico, así que este
script mantiene su propia serie temporal en data/metrics-history.json y
publica el estado actual en docs/metrics.json para que el sitio lo consuma.

Uso:
  python3 scripts/metrics.py
  python3 scripts/metrics.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("Falta PyYAML.  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent


def api(path: str) -> list | dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "medsemiotics-metrics",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: la API devolvió {e.code} para {path}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: sin acceso a la API de GitHub ({e.reason})")


def collect(cfg: dict) -> dict:
    repo = cfg["show"]["audio_repo"]
    releases = {r["tag_name"]: r for r in api(f"/repos/{repo}/releases?per_page=100")}

    episodes, total = [], 0
    for ep in sorted(cfg["episodes"], key=lambda e: e["number"], reverse=True):
        rel = releases.get(ep["tag"])
        asset = None
        if rel:
            asset = next((a for a in rel.get("assets", [])
                          if a["name"] == ep["audio_file"]), None)
        downloads = int(asset["download_count"]) if asset else 0
        total += downloads
        episodes.append({
            "slug": ep["slug"],
            "number": ep["number"],
            "title": ep["title"],
            "published": ep["pub_date"],
            "downloads": downloads,
            "size_bytes": int(asset["size"]) if asset else None,
            "released": bool(asset),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": repo,
        "total_downloads": total,
        "episode_count": len(episodes),
        "episodes": episodes,
    }


def update_history(snapshot: dict, path: Path) -> list:
    history = []
    if path.exists():
        history = json.loads(path.read_text(encoding="utf-8"))

    today = snapshot["generated_at"][:10]
    entry = {
        "date": today,
        "total": snapshot["total_downloads"],
        "by_episode": {e["slug"]: e["downloads"] for e in snapshot["episodes"]},
    }
    # Una sola muestra por día: la última gana si el job corre más de una vez.
    history = [h for h in history if h["date"] != today]
    history.append(entry)
    history.sort(key=lambda h: h["date"])
    return history


def add_deltas(snapshot: dict, history: list) -> None:
    """Descargas nuevas desde la muestra anterior — el dato que de verdad se lee."""
    if len(history) < 2:
        return
    prev = history[-2]["by_episode"]
    snapshot["delta_since"] = history[-2]["date"]
    snapshot["total_delta"] = snapshot["total_downloads"] - history[-2]["total"]
    for ep in snapshot["episodes"]:
        ep["delta"] = ep["downloads"] - prev.get(ep["slug"], 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "podcast.yml"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    snapshot = collect(cfg)

    hist_path = ROOT / "data" / "metrics-history.json"
    history = update_history(snapshot, hist_path)
    add_deltas(snapshot, history)

    if args.dry_run:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
        return

    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

    out = ROOT / "docs" / "metrics.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    print(f"total {snapshot['total_downloads']:,} descargas "
          f"({snapshot.get('total_delta', 0):+,} desde "
          f"{snapshot.get('delta_since', 'la primera muestra')})")
    for e in snapshot["episodes"]:
        mark = "" if e["released"] else "  [sin release]"
        print(f"  ep{e['number']:03d}  {e['downloads']:>7,}"
              f"  {e['title'][:44]}{mark}")


if __name__ == "__main__":
    main()
