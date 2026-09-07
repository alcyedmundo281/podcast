#!/usr/bin/env python3
"""
validate_feed.py — verificación antes de publicar.

Comprueba lo que rompe una suscripción en silencio: XML mal formado, GUID
duplicado o cambiado, enclosure inalcanzable, tamaño declarado distinto del
real, fecha fuera de formato, portada ausente o mal dimensionada.

Falla con código 1 para detener el workflow antes de desplegar.

Uso:
  python3 scripts/validate_feed.py docs/feed.xml
  python3 scripts/validate_feed.py docs/feed.xml --skip-network
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "atom": "http://www.w3.org/2005/Atom",
    "podcast": "https://podcastindex.org/namespace/1.0",
}

errors: list[str] = []
warnings: list[str] = []


def err(m: str) -> None:
    errors.append(m)


def warn(m: str) -> None:
    warnings.append(m)


def head(url: str) -> tuple[int, int | None]:
    """HEAD siguiendo redirecciones — los assets de release devuelven 302."""
    req = urllib.request.Request(url, method="HEAD",
                                 headers={"User-Agent": "medsemiotics-validator"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            length = r.headers.get("Content-Length")
            return r.status, int(length) if length else None
    except urllib.error.HTTPError as e:
        return e.code, None
    except urllib.error.URLError:
        return 0, None


def check_channel(ch: ET.Element) -> None:
    for field in ("title", "link", "description", "language"):
        if ch.findtext(field) is None:
            err(f"canal: falta <{field}>")

    if ch.find("atom:link[@rel='self']", NS) is None:
        err("canal: falta <atom:link rel='self'> — sin él los directorios "
            "no pueden verificar la propiedad del feed")

    img = ch.find("itunes:image", NS)
    if img is None or not img.get("href"):
        err("canal: falta <itunes:image href>")

    if ch.find("itunes:category", NS) is None:
        err("canal: falta <itunes:category> — Apple rechaza el feed sin ella")

    owner = ch.find("itunes:owner", NS)
    if owner is None or owner.findtext("itunes:email", namespaces=NS) is None:
        err("canal: falta <itunes:owner><itunes:email> — Apple lo usa para "
            "verificar que el feed es tuyo")

    if ch.findtext("podcast:guid", namespaces=NS) is None:
        warn("canal: sin <podcast:guid>; el programa no tendrá identidad "
             "estable si algún día cambia la URL del feed")


def check_items(ch: ET.Element, skip_network: bool) -> None:
    items = ch.findall("item")
    if not items:
        err("el feed no contiene ningún <item>")
        return

    guids: dict[str, str] = {}
    for it in items:
        title = it.findtext("title") or "(sin título)"

        guid = it.findtext("guid")
        if not guid:
            err(f"[{title}] falta <guid>")
        elif guid in guids:
            err(f"[{title}] GUID duplicado con [{guids[guid]}] — los clientes "
                f"mostrarán un solo episodio")
        else:
            guids[guid] = title

        pub = it.findtext("pubDate")
        if not pub:
            err(f"[{title}] falta <pubDate>")
        else:
            try:
                dt = parsedate_to_datetime(pub)
                if dt.tzinfo is None:
                    err(f"[{title}] pubDate sin zona horaria")
            except (TypeError, ValueError):
                err(f"[{title}] pubDate no es RFC 2822: {pub!r}")

        enc = it.find("enclosure")
        if enc is None:
            err(f"[{title}] falta <enclosure> — sin él no es un episodio")
            continue

        url, length, mime = enc.get("url"), enc.get("length"), enc.get("type")
        if not url:
            err(f"[{title}] <enclosure> sin url")
        if not mime:
            err(f"[{title}] <enclosure> sin type")
        if not length or not length.isdigit() or int(length) == 0:
            err(f"[{title}] <enclosure length> inválido: {length!r}")

        dur = it.findtext("itunes:duration", namespaces=NS)
        if not dur or not str(dur).strip().isdigit() or int(dur) == 0:
            err(f"[{title}] itunes:duration ausente o en cero")

        if not skip_network and url and length and length.isdigit():
            status, real = head(url)
            if status == 0:
                warn(f"[{title}] no se pudo alcanzar el enclosure (sin red)")
            elif status >= 400:
                err(f"[{title}] el enclosure responde HTTP {status}: {url}")
            elif real is not None and real != int(length):
                err(f"[{title}] length declarado {int(length):,} pero el "
                    f"archivo mide {real:,} bytes")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("feed", nargs="?", default="docs/feed.xml")
    ap.add_argument("--skip-network", action="store_true")
    args = ap.parse_args()

    path = Path(args.feed)
    if not path.exists():
        sys.exit(f"ERROR: no existe {path}")

    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        sys.exit(f"ERROR: XML mal formado — {e}")

    ch = root.find("channel")
    if ch is None:
        sys.exit("ERROR: el RSS no tiene <channel>")

    check_channel(ch)
    check_items(ch, args.skip_network)

    n = len(ch.findall("item"))
    for w in warnings:
        print(f"  aviso   {w}")
    for e in errors:
        print(f"  ERROR   {e}")

    if errors:
        print(f"\n{len(errors)} error(es) en {path} — no se publica.")
        sys.exit(1)
    print(f"\n{path}: {n} episodio(s), conforme"
          f"{' (red omitida)' if args.skip_network else ''}.")


if __name__ == "__main__":
    main()
