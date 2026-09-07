#!/usr/bin/env python3
"""
check_slugs.py — impide cambiar el slug de un episodio ya publicado.

El GUID de cada item del feed deriva del slug. Cambiar uno que ya salió hace
que todos los clientes traten el episodio como nuevo y lo vuelvan a descargar,
y no hay forma de deshacerlo desde el feed.

Compara los slugs del podcast.yml en el índice de git contra los de HEAD.
Añadir episodios es libre; renombrar o borrar uno existente falla.
"""

from __future__ import annotations

import subprocess
import sys

import yaml


def slugs_de(ref: str) -> set[str] | None:
    """Slugs de podcast.yml en una ref de git, o None si el archivo no existe."""
    try:
        raw = subprocess.run(  # noqa: S603
            ["git", "show", f"{ref}:podcast.yml"],  # noqa: S607
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    cfg = yaml.safe_load(raw) or {}
    return {ep["slug"] for ep in cfg.get("episodes") or []}


def main() -> None:
    antes = slugs_de("HEAD")
    if antes is None:
        return  # primer commit: no hay nada contra qué comparar

    ahora = slugs_de(":0")
    if ahora is None:
        return

    perdidos = antes - ahora
    if perdidos:
        print("Slugs de episodio eliminados o renombrados:", file=sys.stderr)
        for s in sorted(perdidos):
            print(f"  - {s}", file=sys.stderr)
        print(
            "\nEl GUID del feed deriva del slug. Cambiar uno ya publicado hace\n"
            "que todos los suscriptores vuelvan a descargar el episodio como\n"
            "si fuera nuevo, y es irreversible.\n\n"
            "Si el episodio nunca se publicó, salta esta comprobación con:\n"
            "  git commit --no-verify",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
