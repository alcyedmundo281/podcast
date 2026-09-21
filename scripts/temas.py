#!/usr/bin/env python3
"""
temas.py — puente entre farmacosemiotics y el podcast.

El audio de cada episodio lo genera NotebookLM (Audio Overview) a partir de un
tema de farmacosemiotics. Ese paso vive en el navegador y no se puede
automatizar desde el repositorio: necesita una sesión de Google. Lo que sí es
mecánico es todo lo que lo rodea, y es lo que hace este script.

  listar     qué temas de farmacosemiotics ya tienen episodio y cuáles no
  preparar   deja listo el material de un tema para pegarlo en NotebookLM

`preparar` escribe tres archivos en notebooklm/<slug>/:

  fuente.md    el YAML del tema convertido a texto legible. Va a NotebookLM
               como «Copied text», no como URL: una fuente curada produce
               mejores Audio Overviews que dejar que rastree la página.
  prompt.txt   el prompt de personalización del Audio Overview, con el tema
               ya incrustado. Generar sin prompt propio da un resultado
               genérico.
  entrada.yml  el borrador de la entrada de podcast.yml, con lo derivable ya
               resuelto (slug, topic, source_url, refs) y lo editorial
               marcado como REVISAR.

Uso:
  python3 scripts/temas.py listar   --fuente ../farmacosemiotics
  python3 scripts/temas.py listar   --fuente ../farmacosemiotics --pendientes
  python3 scripts/temas.py preparar SEL0003 --fuente ../farmacosemiotics
"""

from __future__ import annotations

import argparse
import sys
import textwrap
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    sys.exit("Falta PyYAML.  uv sync --frozen")

type JSON = dict[str, Any]

RAIZ = Path(__file__).resolve().parent.parent

# Carpetas de farmacosemiotics que contienen temas publicables, y el prefijo de
# id que usa cada una. Las fichas son fármaco por indicación; las selecciones
# son el informe por problema de salud que decide cuál se elige.
COLECCIONES = {
    "selecciones": "SEL",
    "fichas": "FT",
}

# La fuente canónica de un episodio es el YAML del tema en el repositorio de
# farmacosemiotics. Los primeros episodios enlazaban la página del sitio; se
# siguen reconociendo para que `listar` no los dé por pendientes.
BASE_FUENTE = "https://github.com/alcyedmundo281/farmacosemiotics/blob/main"
BASE_SITIO = "https://powersemiotics.com/farmacosemiotics"

# Campos que no aportan nada a un guion de audio: metadatos de control
# documental, autoría y licencia. Se excluyen de fuente.md para que NotebookLM
# no los tome por contenido.
OMITIR = frozenset(
    {
        "id",
        "tipo",
        "estado",
        "fecha",
        "actualizado",
        "idioma",
        "autores",
        "licencia",
    }
)


@dataclass(frozen=True)
class Tema:
    """Un tema de farmacosemiotics: una selección o una ficha."""

    ident: str
    coleccion: str
    ruta: Path
    slug: str
    titulo: str

    @property
    def url(self) -> str:
        return f"{BASE_FUENTE}/{self.coleccion}/{self.ruta.name}"

    @property
    def urls(self) -> tuple[str, str]:
        """Todas las formas con que un episodio puede citar este tema."""
        return self.url, f"{BASE_SITIO}/{self.coleccion}/{self.ruta.stem}.html"

    def episodio(self, publicados: dict[str, int]) -> int | None:
        for url in self.urls:
            if url in publicados:
                return publicados[url]
        return None


def morir(msg: str) -> None:
    sys.exit(f"ERROR: {msg}")


def sin_acentos(texto: str) -> str:
    desc = unicodedata.normalize("NFD", texto)
    return "".join(c for c in desc if unicodedata.category(c) != "Mn")


def titulo_de(datos: JSON, coleccion: str) -> str:
    """El rótulo humano del tema, según el tipo de documento."""
    if coleccion == "selecciones":
        return str(datos.get("problema") or "(sin problema)")
    return str(datos.get("titulo") or datos.get("indicacion") or "(sin título)")


def cargar_temas(fuente: Path) -> list[Tema]:
    if not fuente.is_dir():
        morir(f"no existe el directorio de farmacosemiotics: {fuente}")

    temas: list[Tema] = []
    for coleccion, prefijo in COLECCIONES.items():
        carpeta = fuente / coleccion
        if not carpeta.is_dir():
            continue
        for ruta in sorted(carpeta.glob("*.yaml")):
            datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
            # El stem es <PREFIJO><NNNN>-<slug>; el slug es lo que va al feed.
            ident, _, slug = ruta.stem.partition("-")
            if not ident.startswith(prefijo):
                continue
            temas.append(
                Tema(
                    ident=ident,
                    coleccion=coleccion,
                    ruta=ruta,
                    slug=slug,
                    titulo=titulo_de(datos, coleccion),
                )
            )
    if not temas:
        morir(f"{fuente} no contiene temas en {'/, '.join(COLECCIONES)}/")
    return temas


def episodios_por_url(config: Path) -> dict[str, int]:
    """{source_url: número de episodio} de los episodios ya publicados."""
    if not config.exists():
        return {}
    cfg = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    salida: dict[str, int] = {}
    for ep in cfg.get("episodes") or []:
        url = ep.get("source_url")
        if url:
            salida[str(url).rstrip("/")] = int(ep["number"])
    return salida


# --------------------------------------------------------------------------- #
#  YAML -> texto legible para NotebookLM
# --------------------------------------------------------------------------- #


def _rotulo(clave: str) -> str:
    return clave.replace("_", " ").capitalize()


def render(valor: object, nivel: int = 0) -> list[str]:
    """Convierte un valor YAML en líneas Markdown, recursivamente."""
    lineas: list[str] = []
    sangria = "  " * max(nivel - 2, 0)

    if isinstance(valor, dict):
        for clave, sub in valor.items():
            if nivel == 0 and clave in OMITIR:
                continue
            if isinstance(sub, str | int | float) or sub is None:
                if sub is None or str(sub).strip() == "":
                    continue
                texto = " ".join(str(sub).split())
                if nivel == 0:
                    lineas.append(f"\n## {_rotulo(clave)}\n")
                    lineas.append(texto)
                else:
                    lineas.append(f"{sangria}- **{_rotulo(clave)}:** {texto}")
            else:
                if nivel == 0:
                    lineas.append(f"\n## {_rotulo(clave)}\n")
                else:
                    lineas.append(f"{sangria}- **{_rotulo(clave)}:**")
                lineas.extend(render(sub, nivel + 1))
    elif isinstance(valor, list):
        for i, item in enumerate(valor, 1):
            if isinstance(item, dict):
                if nivel <= 1:
                    lineas.append(f"\n### {i}\n")
                lineas.extend(render(item, nivel + 1))
            else:
                lineas.append(f"{sangria}- {' '.join(str(item).split())}")
    else:
        lineas.append(f"{sangria}{' '.join(str(valor).split())}")

    return lineas


def construir_fuente(tema: Tema, datos: JSON) -> str:
    cuerpo = "\n".join(render(datos))
    return (
        f"# {tema.titulo}\n\n"
        f"Documento de farmacosemiotics ({tema.ident}). "
        f"Fuente canónica: {tema.url}\n\n"
        f"Todas las cifras de eficacia y seguridad de este documento están "
        f"ancladas a un PMID que resuelve en PubMed. No inventes datos que no "
        f"aparezcan aquí.\n"
        f"{cuerpo}\n"
    )


# --------------------------------------------------------------------------- #
#  Prompt del Audio Overview
# --------------------------------------------------------------------------- #

PROMPT = """\
Conversación en español entre dos presentadores, para el podcast medsemiotics.
La audiencia es clínica: médicos internistas, residentes y estudiantes de
medicina avanzados. Duración objetivo: entre 15 y 20 minutos.

Tema: {titulo}

{encuadre}

Reglas que no se negocian:

- Usa la terminología clínica exacta del documento. No la simplifiques ni la
  sustituyas por sinónimos coloquiales. Los nombres de los fármacos son
  denominaciones comunes internacionales: pronúncialos tal cual.
- Cita las cifras concretas del documento —NNT, certeza GRADE, tamaños de
  efecto, umbrales— cuando sostengan un argumento. Si una cifra no está en el
  documento, no la menciones.
- No inventes estudios, guías ni recomendaciones que no estén en la fuente.
- Prioriza lo contraintuitivo: el punto donde un clínico razonable se
  equivocaría. Ese es el eje del episodio, no un resumen plano.
- Estructura en tres movimientos: el caso o el problema, el razonamiento que
  lo resuelve, y qué hacer con ello en la consulta.
- Cierra con lo que el oyente debe recordar mañana, no con un resumen.

Evita el tono publicitario y las frases de relleno. Es un episodio para
alguien que va a tomar decisiones con esto.
"""

ENCUADRES = {
    "selecciones": (
        "Este documento es un informe de selección: compara candidatos en "
        "eficacia, seguridad, conveniencia y costo, y concluye cuál se elige. "
        "El interés del episodio está en el criterio decisorio —por qué gana "
        "el que gana—, no en recitar la tabla de candidatos uno por uno."
    ),
    "fichas": (
        "Este documento es una ficha de farmacoterapia: la molécula ya está "
        "elegida y lo que sigue es usarla bien —cribado previo, posología, "
        "umbrales de suspensión, interacciones, seguridad reproductiva y "
        "atención compartida—. El episodio debe servir para manejar al "
        "paciente que ya lleva el fármaco."
    ),
}


def construir_prompt(tema: Tema) -> str:
    return PROMPT.format(
        titulo=tema.titulo,
        encuadre=ENCUADRES.get(tema.coleccion, ""),
    )


# --------------------------------------------------------------------------- #
#  Borrador de la entrada de podcast.yml
# --------------------------------------------------------------------------- #


def construir_entrada(tema: Tema, datos: JSON, numero: int) -> str:
    pista = datos.get("conclusion") or datos.get("pregunta") or ""
    # El YAML del feed pliega la descripción con `>-`; se envuelve a mano para
    # no dejar una línea de 400 caracteres entre entradas de 75.
    pista_txt = textwrap.fill(
        " ".join(str(pista).split()),
        width=72,
        initial_indent="      ",
        subsequent_indent="      ",
        # Sin esto textwrap parte por el guion, y el escalar plegado de YAML
        # vuelve a unir las líneas con un espacio: «renina- angiotensina».
        break_on_hyphens=False,
        break_long_words=False,
    )
    # Offset fijo y no ZoneInfo: en Windows no hay base de zonas sin el paquete
    # tzdata, y Ecuador no tiene horario de verano.
    ahora = datetime.now(timezone(timedelta(hours=-5)))
    refs = datos.get("refs") or []

    return f"""\
# Borrador para podcast.yml — tema {tema.ident}
#
# Lo derivable ya está resuelto. Los campos marcados REVISAR son editoriales y
# dependen del audio que devuelva NotebookLM: el título es el gancho del
# episodio, la duración sale del MP3 y la descripción son las notas reales.
#
# El slug NO se cambia una vez publicado: forma el GUID del feed.

  - slug: "{tema.slug}"
    number: {numero}
    season: 1
    title: "REVISAR — {tema.titulo}"
    pub_date: "{ahora.strftime("%Y-%m-%dT%H:%M:00%z")[:-2]}:00"
    duration: "REVISAR"          # HH:MM:SS, del MP3 ya masterizado
    tag: "ep{numero:03d}"
    audio_file: "ep{numero:03d}.mp3"
    topic: "REVISAR/{tema.slug}"   # <especialidad>/<slug>, como en medsemiotics-db
    transcript: "transcripts/ep{numero:03d}.vtt"
    source_url: "{tema.url}"
    description: >-
      REVISAR — notas del episodio. Punto de partida, de la conclusión del
      documento:

{pista_txt}

# Referencias del documento fuente ({len(refs)}): {", ".join(str(r) for r in refs) or "(ninguna)"}
"""


# --------------------------------------------------------------------------- #
#  Subcomandos
# --------------------------------------------------------------------------- #


def cmd_listar(args: argparse.Namespace) -> int:
    temas = cargar_temas(Path(args.fuente))
    publicados = episodios_por_url(Path(args.config))

    pendientes = 0
    coleccion_actual = ""
    for tema in temas:
        numero = tema.episodio(publicados)
        if numero is None:
            pendientes += 1
        elif args.pendientes:
            continue
        if tema.coleccion != coleccion_actual:
            coleccion_actual = tema.coleccion
            print(f"\n{coleccion_actual}/")
        marca = f"ep{numero:03d}" if numero else "  —  "
        print(f"  {marca}  {tema.ident}  {tema.titulo[:62]}")

    print(
        f"\n{len(temas)} temas · {len(temas) - pendientes} con episodio · {pendientes} pendientes"
    )
    return 0


def cmd_preparar(args: argparse.Namespace) -> int:
    temas = cargar_temas(Path(args.fuente))
    ident = args.ident.upper()

    elegidos = [
        t for t in temas if t.ident == ident or sin_acentos(t.slug) == ident.lower()
    ]
    if not elegidos:
        morir(
            f"no existe el tema {args.ident!r}. Usa `listar` para ver los disponibles."
        )
    tema = elegidos[0]

    config = Path(args.config)
    publicados = episodios_por_url(config)
    numero_publicado = tema.episodio(publicados)
    if numero_publicado is not None:
        morir(
            f"{tema.ident} ya es el episodio {numero_publicado}. "
            "Los temas no se republican."
        )

    cfg = yaml.safe_load(config.read_text(encoding="utf-8")) if config.exists() else {}
    numeros = [int(e["number"]) for e in (cfg or {}).get("episodes") or []]
    numero = max(numeros, default=0) + 1

    datos = yaml.safe_load(tema.ruta.read_text(encoding="utf-8")) or {}
    destino = Path(args.salida) / tema.slug
    destino.mkdir(parents=True, exist_ok=True)

    archivos = {
        "fuente.md": construir_fuente(tema, datos),
        "prompt.txt": construir_prompt(tema),
        "entrada.yml": construir_entrada(tema, datos, numero),
    }
    for nombre, contenido in archivos.items():
        (destino / nombre).write_text(contenido, encoding="utf-8")

    print(f"{tema.ident} · {tema.titulo}")
    print(f"  episodio propuesto: ep{numero:03d}   slug: {tema.slug}")
    print(f"  escrito en {destino}/")
    for nombre, contenido in archivos.items():
        print(f"    {nombre:<12} {len(contenido):>7,} bytes")
    print(
        "\nSiguiente paso, en tu máquina (NotebookLM necesita navegador y sesión\n"
        "de Google; no se puede hacer desde el repositorio):\n"
        f"  1. Crea un cuaderno y añade fuente.md como «Copied text».\n"
        f"  2. Studio -> Audio Overview -> personalizar, y pega prompt.txt.\n"
        f"  3. Descarga el MP3, masterízalo y publícalo como release ep{numero:03d}.\n"
        f"  4. Pega entrada.yml en podcast.yml, completa los REVISAR y haz push."
    )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config",
        default=str(RAIZ / "podcast.yml"),
        help="podcast.yml del que leer los episodios ya publicados",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("listar", help="temas con y sin episodio")
    pl.add_argument("--fuente", required=True, help="clon de farmacosemiotics")
    pl.add_argument("--pendientes", action="store_true", help="solo los que faltan")
    pl.set_defaults(func=cmd_listar)

    pp = sub.add_parser("preparar", help="material de un tema para NotebookLM")
    pp.add_argument("ident", help="id del tema (p. ej. SEL0003) o su slug")
    pp.add_argument("--fuente", required=True, help="clon de farmacosemiotics")
    pp.add_argument("--salida", default=str(RAIZ / "notebooklm"))
    pp.set_defaults(func=cmd_preparar)

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
