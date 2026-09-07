#!/usr/bin/env python3
"""
build_feed.py — compila podcast.yml a docs/feed.xml y docs/index.html

Arquitectura:
  - El audio vive como asset de un GitHub Release, no en el repositorio.
    GitHub no limita ni el tamaño total ni el ancho de banda de los assets
    de release, mientras que GitHub Pages tiene un techo de 1 GB por sitio.
  - La URL y el tamaño en bytes del <enclosure> se resuelven contra la API
    de releases, de modo que nunca se escriben a mano en podcast.yml.
  - Sin dependencias de red en el sitio publicado: la salida es XML y HTML
    estáticos.

Uso:
  python3 scripts/build_feed.py                # consulta la API de releases
  python3 scripts/build_feed.py --offline      # usa size_bytes de podcast.yml
  python3 scripts/build_feed.py --out docs

Dependencia de construcción: PyYAML (fijada en requirements.txt).
En tiempo de ejecución el sitio no depende de nada.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

try:
    import yaml
except ImportError:
    sys.exit("Falta PyYAML.  pip install -r requirements.txt")

# UUID de espacio de nombres definido por la especificación Podcasting 2.0
# para derivar <podcast:guid> a partir de la URL del feed.
PODCAST_NS_UUID = uuid.UUID("ead4c236-bf58-58c6-a2c6-a6b28d128cb6")

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
#  Utilidades
# --------------------------------------------------------------------------- #

def die(msg: str) -> None:
    sys.exit(f"ERROR: {msg}")


def rfc2822(value: str) -> str:
    """ISO 8601 con zona horaria -> fecha RFC 2822, que es lo que exige RSS."""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        die(f"pub_date no es ISO 8601 válido: {value!r}")
    if dt.tzinfo is None:
        die(f"pub_date debe llevar zona horaria (p. ej. -05:00): {value!r}")
    return format_datetime(dt)


def duration_seconds(value: str) -> int:
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return h * 3600 + m * 60 + s


def tag(name: str, text, **attrs) -> str:
    a = "".join(f" {k.replace('_', ':')}={quoteattr(str(v))}" for k, v in attrs.items())
    if text is None:
        return f"<{name}{a}/>"
    return f"<{name}{a}>{escape(str(text))}</{name}>"


def cdata(name: str, text: str) -> str:
    safe = str(text).replace("]]>", "]]]]><![CDATA[>")
    return f"<{name}><![CDATA[{safe}]]></{name}>"


# --------------------------------------------------------------------------- #
#  Resolución de assets de release
# --------------------------------------------------------------------------- #

def fetch_release_assets(repo: str) -> dict[str, dict[str, dict]]:
    """{tag_name: {asset_name: {...}}} desde la API de releases de GitHub."""
    index: dict[str, dict[str, dict]] = {}
    page = 1
    token = os.environ.get("GITHUB_TOKEN", "")
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "medsemiotics-feed-builder",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                batch = json.load(resp)
        except urllib.error.HTTPError as e:
            die(f"API de releases devolvió {e.code} para {repo}. "
                f"¿El repo existe y es público, o falta GITHUB_TOKEN? "
                f"Puedes construir sin red con --offline.")
        except urllib.error.URLError as e:
            die(f"Sin acceso a la API de GitHub ({e.reason}). Usa --offline.")
        if not batch:
            break
        for rel in batch:
            index[rel["tag_name"]] = {a["name"]: a for a in rel.get("assets", [])}
        if len(batch) < 100:
            break
        page += 1
    return index


def resolve_enclosure(ep: dict, repo: str, assets: dict | None) -> tuple[str, int]:
    tag_name, filename = ep["tag"], ep["audio_file"]
    url = f"https://github.com/{repo}/releases/download/{tag_name}/{filename}"

    if assets is None:                                    # modo --offline
        size = ep.get("size_bytes")
        if not size:
            die(f"[{ep['slug']}] en modo --offline hace falta size_bytes")
        return url, int(size)

    if tag_name not in assets:
        die(f"[{ep['slug']}] no existe el release con tag {tag_name!r} en {repo}")
    if filename not in assets[tag_name]:
        have = ", ".join(assets[tag_name]) or "(ninguno)"
        die(f"[{ep['slug']}] el release {tag_name!r} no contiene {filename!r}. "
            f"Assets presentes: {have}")
    return url, int(assets[tag_name][filename]["size"])


# --------------------------------------------------------------------------- #
#  Construcción del feed
# --------------------------------------------------------------------------- #

REQUIRED_EP = ("slug", "number", "title", "pub_date", "duration",
               "tag", "audio_file", "description")


def build_feed(cfg: dict, offline: bool) -> str:
    show = cfg["show"]
    base = show["base_url"]
    if not base.endswith("/"):
        die("show.base_url debe terminar en '/'")
    feed_url = base + "feed.xml"
    repo = show["audio_repo"]

    episodes = cfg.get("episodes") or []
    if not episodes:
        die("podcast.yml no contiene episodios")

    seen = set()
    for ep in episodes:
        for field in REQUIRED_EP:
            if not ep.get(field):
                die(f"episodio {ep.get('slug', '?')!r}: falta el campo {field!r}")
        if ep["slug"] in seen:
            die(f"slug duplicado: {ep['slug']!r} — los slugs forman el GUID")
        seen.add(ep["slug"])

    assets = None if offline else fetch_release_assets(repo)

    # ----- canal -----------------------------------------------------------
    explicit = "true" if show.get("explicit") else "false"
    channel_guid = str(uuid.uuid5(
        PODCAST_NS_UUID,
        feed_url.split("://", 1)[-1].rstrip("/")))

    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append(
        '<rss version="2.0" '
        'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:podcast="https://podcastindex.org/namespace/1.0">')
    out.append("<channel>")

    out.append(tag("title", show["title"]))
    out.append(tag("link", show["link"]))
    out.append(tag("language", show["language"]))
    out.append(tag("copyright", show.get("copyright", "")))
    out.append(tag("description", " ".join(show["description"].split())))
    out.append(tag("lastBuildDate", format_datetime(datetime.now().astimezone())))
    out.append(tag("generator", "medsemiotics build_feed.py"))
    out.append(f'<atom:link href={quoteattr(feed_url)} rel="self" '
               f'type="application/rss+xml"/>')

    out.append(tag("itunes:author", show["author"]))
    out.append(tag("itunes:summary", " ".join(show["description"].split())))
    if show.get("subtitle"):
        out.append(tag("itunes:subtitle", show["subtitle"]))
    out.append(tag("itunes:explicit", explicit))
    out.append(tag("itunes:type", show.get("type", "episodic")))
    out.append(f'<itunes:image href={quoteattr(base + show["image"])}/>')
    out.append("<itunes:owner>"
               + tag("itunes:name", show["owner_name"])
               + tag("itunes:email", show["owner_email"])
               + "</itunes:owner>")
    if show.get("keywords"):
        out.append(tag("itunes:keywords", ",".join(show["keywords"])))

    for cat in show.get("categories", []):
        if ">" in cat:
            parent, child = (p.strip() for p in cat.split(">", 1))
            out.append(f"<itunes:category text={quoteattr(parent)}>"
                       f"<itunes:category text={quoteattr(child)}/>"
                       f"</itunes:category>")
        else:
            out.append(f"<itunes:category text={quoteattr(cat)}/>")

    # Podcasting 2.0: identidad estable del programa, independiente de la URL.
    out.append(tag("podcast:guid", channel_guid))
    out.append(f'<podcast:locked owner={quoteattr(show["owner_email"])}>yes'
               f'</podcast:locked>')

    # ----- episodios --------------------------------------------------------
    for ep in sorted(episodes, key=lambda e: e["number"], reverse=True):
        url, size = resolve_enclosure(ep, repo, assets)
        item = ["<item>"]
        item.append(tag("title", ep["title"]))
        item.append(tag("guid", f"{base}{ep['slug']}", isPermaLink="false"))
        item.append(tag("pubDate", rfc2822(ep["pub_date"])))
        item.append(tag("link", ep.get("source_url", show["link"])))
        item.append(tag("description", " ".join(str(ep["description"]).split())))
        item.append(cdata("content:encoded", ep["description"]))
        item.append(f'<enclosure url={quoteattr(url)} length="{size}" '
                    f'type="audio/mpeg"/>')
        item.append(tag("itunes:duration", duration_seconds(ep["duration"])))
        item.append(tag("itunes:episode", ep["number"]))
        item.append(tag("itunes:season", ep.get("season", 1)))
        item.append(tag("itunes:episodeType", "full"))
        item.append(tag("itunes:explicit",
                        "true" if ep.get("explicit", show.get("explicit")) else "false"))
        item.append(tag("itunes:author", show["author"]))
        if ep.get("transcript"):
            item.append(f'<podcast:transcript '
                        f'url={quoteattr(base + ep["transcript"])} '
                        f'type="text/vtt" language="{show["language"]}"/>')
        item.append("</item>")
        out.append("".join(item))

    out.append("</channel>")
    out.append("</rss>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
#  Página índice
# --------------------------------------------------------------------------- #

def build_index(cfg: dict) -> str:
    show = cfg["show"]
    base = show["base_url"]
    rows = []
    for ep in sorted(cfg["episodes"], key=lambda e: e["number"], reverse=True):
        d = datetime.fromisoformat(ep["pub_date"]).strftime("%d.%m.%Y")
        src = ep.get("source_url")
        link = (f'<a href="{html.escape(src)}">Artículo completo &rarr;</a>'
                if src else "")
        rows.append(f"""    <article>
      <h2>{ep['number']}. {html.escape(ep['title'])}</h2>
      <p class="meta">{d} &middot; {html.escape(str(ep['duration']))}</p>
      <p>{html.escape(" ".join(str(ep['description']).split()))}</p>
      <p>{link}</p>
    </article>""")

    return f"""<!doctype html>
<html lang="{show['language']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(show['title'])} — podcast</title>
<link rel="alternate" type="application/rss+xml"
      title="{html.escape(show['title'])}" href="{base}feed.xml">
<style>
  :root {{ --bg:#fbfaf8; --fg:#1a1a1a; --mut:#6b6b6b; --rule:#e2ddd6; --acc:#7a3b2e; }}
  @media (prefers-color-scheme:dark) {{
    :root:not([data-theme=light]) {{ --bg:#14130f; --fg:#ece7de; --mut:#9c968b;
      --rule:#2e2b25; --acc:#c98a72; }} }}
  * {{ box-sizing:border-box }}
  body {{ background:var(--bg); color:var(--fg); margin:0;
    font:16px/1.65 Georgia,'Iowan Old Style',serif; }}
  main {{ max-width:44rem; margin:0 auto; padding:4rem 1.5rem 6rem; }}
  h1 {{ font-size:2rem; margin:0 0 .3rem; letter-spacing:-.01em }}
  .sub {{ color:var(--mut); margin:0 0 2rem; font-style:italic }}
  .sub a {{ color:var(--acc) }}
  article {{ border-top:1px solid var(--rule); padding:1.75rem 0 .25rem }}
  h2 {{ font-size:1.15rem; margin:0 0 .25rem; font-weight:600 }}
  .meta {{ color:var(--mut); font-size:.85rem; margin:0 0 .7rem;
    font-variant-numeric:tabular-nums }}
  a {{ color:var(--acc) }}
  footer {{ margin-top:3rem; color:var(--mut); font-size:.85rem }}
</style>
</head>
<body>
<main>
  <h1>{html.escape(show['title'])}</h1>
  <p class="sub">{html.escape(show.get('subtitle',''))} &middot;
     <a href="{base}feed.xml">Feed RSS</a></p>
{chr(10).join(rows)}
  <footer>{html.escape(show.get('copyright',''))} &middot;
     <a href="{html.escape(show['link'])}">medsemiotics</a></footer>
</main>
</body>
</html>
"""


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "podcast.yml"))
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--offline", action="store_true",
                    help="no consultar la API; usar size_bytes de podcast.yml")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    feed = build_feed(cfg, args.offline)
    (outdir / "feed.xml").write_text(feed, encoding="utf-8")
    (outdir / "index.html").write_text(build_index(cfg), encoding="utf-8")

    print(f"feed.xml     {len(feed):>7,} bytes  "
          f"{len(cfg['episodes'])} episodios"
          f"{'  [offline]' if args.offline else ''}")
    print(f"index.html   escrito en {outdir}")


if __name__ == "__main__":
    main()
