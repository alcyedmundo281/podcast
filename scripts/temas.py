#!/usr/bin/env python3
"""
temas.py — puente entre el ecosistema Powersemiotics y el podcast.

El audio de cada episodio lo genera NotebookLM (Audio Overview) a partir de un
tema publicado. Ese paso vive en el navegador y no se puede automatizar desde el
repositorio: necesita una sesión de Google. Lo que sí es mecánico es todo lo que
lo rodea, y es lo que hace este script.

Fuentes que entiende `--fuente`:

  farmacosemiotics   un clon del repositorio: selecciones (SEL) y fichas (FT).
  medsemiotics       el sitio publicado (https://powersemiotics.com/medsemiotics/)
                     o un clon del repositorio. Son candidatos los artículos del
                     blog que ya tienen caso socrático publicado (HM####): el
                     caso da el hilo del episodio y la evidencia de
                     medsemiotics-db, las cifras.
  medsemiotics-copilot
                     un clon del repositorio de la cátedra (UCE / HCAM). Son
                     candidatos los casos socráticos de clase
                     (docs/caso_clinico_socratico_<tema>.md), cruzados con el
                     sílabo oficial; su guía clínica ampliada va detrás del caso.

  listar     qué temas ya tienen episodio y cuáles no
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
  python3 scripts/temas.py listar   --fuente https://powersemiotics.com/medsemiotics/
  python3 scripts/temas.py preparar HM6001 --fuente https://powersemiotics.com/medsemiotics/
  python3 scripts/temas.py listar   --fuente ../medsemiotics-copilot --pendientes
  python3 scripts/temas.py preparar NEURO-DESMIELINIZANTES-EM --fuente ../medsemiotics-copilot
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import textwrap
import unicodedata
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NoReturn

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

# medsemiotics se lee de lo PUBLICADO: el índice del blog y el JSON de cada
# artículo, que ya incluye su caso socrático. La fuente canónica del episodio es
# la página del artículo, como en ep001 y ep003.
SITIO_MED = "https://powersemiotics.com/medsemiotics"
INDICE_MED = "assets/data/blog-index.json"
AGENTE = "medsemiotics-podcast/1.0 (+https://powersemiotics.com/podcast/)"

# medsemiotics-copilot se lee de un clon: los casos socráticos de clase y el
# sílabo oficial que los ubica. La fuente canónica del episodio es el módulo web
# de esa semana, como en ep001 y ep003; el caso en GitHub se reconoce también.
BASE_COPILOT = "https://github.com/alcyedmundo281/medsemiotics-copilot/blob/main"
PATRON_CASO_COPILOT = "caso_clinico_socratico_*.md"
# Versiones del mismo caso para una audiencia: la guía del estudiante es la hoja
# de trabajo sin razonamientos y ya tiene episodio a través del caso base.
VARIANTES_CASO_COPILOT = ("_estudiante", "_docente")
ESPECIALIDADES = {"NEURO": "neurologia", "GASTRO": "gastroenterologia"}

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
    """Un tema publicable: selección o ficha de farmacosemiotics, o caso de medsemiotics."""

    ident: str
    coleccion: str
    slug: str
    titulo: str
    # Todas las formas con que un episodio puede citar este tema; la primera es
    # la canónica y es la que va a `source_url`.
    urls: tuple[str, ...]
    cargar: Callable[[], JSON]
    especialidad: str = "REVISAR"

    @property
    def url(self) -> str:
        return self.urls[0]

    def episodio(self, publicados: dict[str, int]) -> int | None:
        for url in self.urls:
            if url in publicados:
                return publicados[url]
        return None


def morir(msg: str) -> NoReturn:
    sys.exit(f"ERROR: {msg}")


def sin_acentos(texto: str) -> str:
    desc = unicodedata.normalize("NFD", texto)
    return "".join(c for c in desc if unicodedata.category(c) != "Mn")


def titulo_de(datos: JSON, coleccion: str) -> str:
    """El rótulo humano del tema, según el tipo de documento."""
    if coleccion == "selecciones":
        return str(datos.get("problema") or "(sin problema)")
    return str(datos.get("titulo") or datos.get("indicacion") or "(sin título)")


def slugificar(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos(texto).lower()).strip("-")


def es_medsemiotics(fuente: str) -> bool:
    if fuente.startswith(("https://", "http://")):
        return True
    return (Path(fuente) / INDICE_MED).is_file()


def leer_json(fuente: str, relativa: str) -> object:
    """Un JSON de medsemiotics, del sitio publicado o de un clon local."""
    if fuente.startswith(("https://", "http://")):
        url = f"{fuente.rstrip('/')}/{relativa}"
        peticion = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            return json.loads(respuesta.read().decode("utf-8"))
    return json.loads((Path(fuente) / relativa).read_text(encoding="utf-8"))


def cargar_casos(fuente: str) -> list[Tema]:
    """Artículos de medsemiotics con caso socrático publicado."""
    indice = leer_json(fuente, INDICE_MED)
    if not isinstance(indice, list):
        morir(f"{INDICE_MED} de {fuente} no es una lista de artículos")
    temas: list[Tema] = []
    for articulo in indice:
        if not articulo.get("has_caso"):
            continue
        grounding = articulo["grounding"]
        slug_articulo = str(articulo["slug"])
        relativa = f"assets/data/posts/{slug_articulo}.json"

        def cargar(relativa: str = relativa) -> JSON:
            datos = leer_json(fuente, relativa)
            if not isinstance(datos, dict):
                morir(f"{relativa} de {fuente} no es un artículo")
            return datos

        temas.append(
            Tema(
                ident=str(grounding["condicion_id"]).replace(":", ""),
                coleccion="casos",
                slug=slugificar(str(grounding["condicion_nombre"])),
                titulo=str(grounding["condicion_nombre"]),
                urls=(f"{SITIO_MED}/post.html?slug={slug_articulo}",),
                cargar=cargar,
                especialidad=str(articulo.get("category") or "REVISAR"),
            )
        )
    if not temas:
        morir(f"{fuente} no tiene artículos con caso socrático publicado")
    return sorted(temas, key=lambda t: t.ident)


def es_copilot(fuente: str) -> bool:
    raiz = Path(fuente)
    return (raiz / "config" / "syllabi").is_dir() and any(
        (raiz / "docs").glob(PATRON_CASO_COPILOT)
    )


def semanas_del_silabo(raiz: Path) -> dict[str, JSON]:
    """{topic_id: semana} de todos los sílabos oficiales, con el curso incrustado."""
    semanas: dict[str, JSON] = {}
    for ruta in sorted((raiz / "config" / "syllabi").glob("*/silabo_*_v2.yaml")):
        silabo = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        info = silabo.get("course_info") or {}
        for semana in silabo.get("schedule_18_weeks") or []:
            semanas[str(semana["topic_id"])] = {
                **semana,
                "course_code": str(info.get("code", "")),
                "course_name": str(info.get("name", "")),
                "web_hub": str(info.get("web_hub", "")),
            }
    return semanas


def cargar_casos_copilot(fuente: str) -> list[Tema]:
    """Casos socráticos de clase de medsemiotics-copilot, ubicados en su sílabo."""
    raiz = Path(fuente)
    semanas = semanas_del_silabo(raiz)
    temas: list[Tema] = []
    for ruta in sorted((raiz / "docs").glob(PATRON_CASO_COPILOT)):
        if ruta.stem.endswith(VARIANTES_CASO_COPILOT):
            continue
        clave = ruta.stem.removeprefix("caso_clinico_socratico_")
        topic_id = clave.replace("_", "-")
        semana = semanas.get(topic_id, {})
        curso = str(semana.get("course_code") or "")
        prefijo = curso.lower() or "*"
        guias = sorted((raiz / "docs").glob(f"guia_clinica_{prefijo}_{clave}.md"))
        urls = [f"{BASE_COPILOT}/docs/{ruta.name}"]
        # El módulo propio de la semana es la fuente canónica; el hub del curso no
        # identifica a ningún tema y no sirve como source_url.
        modulo = str(semana.get("web_module") or "")
        if modulo and modulo != semana.get("web_hub"):
            urls.insert(0, modulo)

        def cargar(
            caso: Path = ruta, guias: list[Path] = guias, semana: JSON = semana
        ) -> JSON:
            return {
                "caso": caso.read_text(encoding="utf-8"),
                "guia": guias[0].read_text(encoding="utf-8") if guias else "",
                "semana": semana,
            }

        temas.append(
            Tema(
                ident=f"{curso or 'CASO'}-{topic_id}".upper(),
                coleccion="copilot",
                slug=topic_id,
                titulo=str(semana.get("title") or topic_id),
                urls=tuple(urls),
                cargar=cargar,
                especialidad=ESPECIALIDADES.get(curso, "REVISAR"),
            )
        )
    return temas


def cargar_temas(fuente_txt: str) -> list[Tema]:
    if es_copilot(fuente_txt):
        return cargar_casos_copilot(fuente_txt)
    if es_medsemiotics(fuente_txt):
        return cargar_casos(fuente_txt)
    fuente = Path(fuente_txt)
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

            def cargar(ruta: Path = ruta) -> JSON:
                datos: JSON = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
                return datos

            temas.append(
                Tema(
                    ident=ident,
                    coleccion=coleccion,
                    slug=slug,
                    titulo=titulo_de(datos, coleccion),
                    urls=(
                        f"{BASE_FUENTE}/{coleccion}/{ruta.name}",
                        f"{BASE_SITIO}/{coleccion}/{ruta.stem}.html",
                    ),
                    cargar=cargar,
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


def _lineas_datos(datos: list[JSON]) -> list[str]:
    return [f"- {d['etiqueta']}: {d['valor']}" for d in datos]


def construir_fuente_caso(tema: Tema, articulo: JSON) -> str:
    """Artículo de medsemiotics: el caso da el hilo; la evidencia, las cifras."""
    caso: JSON = articulo["caso"]
    triada: JSON = articulo.get("triada") or {}
    partes = [
        f"# {tema.titulo}",
        f"Artículo de medsemiotics ({tema.ident}). Fuente canónica: {tema.url}",
        "Las cifras de evidencia (cocientes de verosimilitud, sensibilidad, "
        "especificidad e intervalos) provienen de medsemiotics-db y cada una "
        "está anclada a una referencia de PubMed. Cuando un hallazgo figura como "
        "«LR no medido» o «LR no medible», ese cociente no existe: no lo inventes "
        "ni lo estimes. El paciente del caso es ficticio.",
        "## Tríada semiótica",
        f"- Signo: {triada.get('significante', '')}",
        f"- Interpretación: {triada.get('significado', '')}",
        f"- Decisión: {triada.get('decision', '')}",
        "## Caso clínico socrático",
        "Objetivos de aprendizaje:",
        *(f"- {o}" for o in caso["objetivos"]),
        f"### {caso['vineta']['titulo']}",
        str(caso["vineta"]["texto"]),
        *_lineas_datos(caso["vineta"]["datos"]),
    ]
    for etapa in caso["etapas"]:
        partes.append(
            f"### Etapa {etapa['numero']} · {etapa['fase_etiqueta']}: {etapa['titulo']}"
        )
        if etapa.get("informacion"):
            partes.append(str(etapa["informacion"]))
        partes.extend(_lineas_datos(etapa["datos"]))
        for h in etapa["hallazgos"]:
            cifras = "; ".join(h["cifras"]) or h["estado"]
            notas = " ".join(
                str(h[k]) for k in ("decision", "motivo", "advertencia") if h.get(k)
            )
            poblacion = f" Población: {h['poblacion']}." if h.get("poblacion") else ""
            partes.append(
                f"- Evidencia de medsemiotics-db · {h['nombre']} ({h['rol']}): "
                f"{cifras}.{poblacion} {notas}".rstrip()
            )
        for p in etapa["preguntas"]:
            partes.append(f"Pregunta socrática: {p['pregunta']}")
            partes.append(f"Razonamiento esperado: {p['clave']}")
    partes += [
        "### Cierre",
        str(caso["cierre"]["sintesis"]),
        "Lo que la evidencia aún no responde:",
        *(f"- {n}" for n in caso["cierre"]["necesidades_aprendizaje"]),
        "## Ficha de evidencia completa (medsemiotics-db)",
        str(articulo.get("body") or ""),
    ]
    return "\n\n".join(partes) + "\n"


def sin_diagramas(markdown: str) -> str:
    """Quita los bloques de código (diagramas mermaid): en audio sólo son ruido."""
    return re.sub(r"```.*?```\n?", "", markdown, flags=re.DOTALL).strip()


def construir_fuente_copilot(tema: Tema, datos: JSON) -> str:
    """Caso socrático de clase: el caso da el hilo; la guía ampliada, el contexto."""
    semana: JSON = datos["semana"]
    ubicacion = (
        f"{semana['course_name']}, semana {semana['week']} ({semana['date']})"
        if semana
        else "caso de clase sin semana en el sílabo"
    )
    partes = [
        f"# {tema.titulo}",
        f"Caso socrático de medsemiotics-copilot ({tema.ident}): {ubicacion}. "
        f"Fuente canónica: {tema.url}",
        "El paciente del caso es sintético. Este material es docente y no trae "
        "cocientes de verosimilitud de medsemiotics-db: no inventes LR, "
        "sensibilidades ni cifras que no aparezcan aquí. Las dosis son referencia "
        "académica sujeta al protocolo institucional; no las presentes como "
        "indicación para un paciente real.",
        "## Caso clínico socrático",
        sin_diagramas(str(datos["caso"])),
    ]
    if datos.get("guia"):
        partes += [
            "## Guía clínica ampliada de la clase",
            sin_diagramas(str(datos["guia"])),
        ]
    return "\n\n".join(partes) + "\n"


def construir_fuente(tema: Tema, datos: JSON) -> str:
    if tema.coleccion == "casos":
        return construir_fuente_caso(tema, datos)
    if tema.coleccion == "copilot":
        return construir_fuente_copilot(tema, datos)
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
    "casos": (
        "Este documento es un caso clínico socrático de medsemiotics construido "
        "sobre la evidencia de medsemiotics-db. Sigue el caso etapa por etapa: "
        "plantea cada pregunta al oyente y deja un silencio breve antes de "
        "razonarla. El eje del episodio es cuánto cambia la probabilidad con cada "
        "hallazgo —y por qué a veces no se puede saber—: si la base declara un "
        "LR no medido o no medible, explica qué significa en vez de dar un número."
    ),
    "copilot": (
        "Este documento es un caso clínico socrático de la cátedra de la "
        "Universidad Central del Ecuador en el Hospital Carlos Andrade Marín, "
        "seguido de la guía clínica de esa clase. Recorre el caso etapa por etapa "
        "(KNOW, REASON, ACT): plantea cada pregunta al oyente, deja un silencio "
        "breve y luego razónala con la clave docente. El eje del episodio es la "
        "semiología que decide el diagnóstico y el error concreto que un clínico "
        "razonable cometería; la guía aporta el contexto, no una lista que recitar."
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


def pista_y_refs(tema: Tema, datos: JSON) -> tuple[str, list[str]]:
    """Punto de partida de las notas del episodio y referencias de la fuente."""
    if tema.coleccion == "casos":
        caso: JSON = datos["caso"]
        refs = [str(r["id"]) for r in caso.get("referencias") or []]
        return str(caso["cierre"]["sintesis"]), refs
    if tema.coleccion == "copilot":
        # La viñeta de entrada (citas «>» del caso) es el gancho natural de las notas.
        vineta = [
            linea.lstrip("> ").strip()
            for linea in str(datos["caso"]).splitlines()
            if linea.startswith(">") and "sintético" not in linea
        ]
        _, _, bibliografia = str(datos.get("guia") or "").partition("Referencias")
        refs = [
            linea[2:].strip()
            for linea in bibliografia.splitlines()
            if linea.startswith("- ")
        ]
        return " ".join(vineta).replace("**", ""), refs
    pista = datos.get("conclusion") or datos.get("pregunta") or ""
    return str(pista), [str(r) for r in datos.get("refs") or []]


def construir_entrada(tema: Tema, datos: JSON, numero: int) -> str:
    pista, refs = pista_y_refs(tema, datos)
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
    topic: "{tema.especialidad}/{tema.slug}"   # <especialidad>/<slug>; completar si dice REVISAR
    transcript: "transcripts/ep{numero:03d}.vtt"
    source_url: "{tema.url}"
    description: >-
      REVISAR — notas del episodio. Punto de partida, de la conclusión del
      documento:

{pista_txt}

# Referencias del documento fuente ({len(refs)}): {", ".join(refs) or "(ninguna)"}
"""


# --------------------------------------------------------------------------- #
#  Subcomandos
# --------------------------------------------------------------------------- #


def cmd_listar(args: argparse.Namespace) -> int:
    temas = cargar_temas(args.fuente)
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
    temas = cargar_temas(args.fuente)
    ident = args.ident.upper().replace(":", "")

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

    datos = tema.cargar()
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


AYUDA_FUENTE = (
    "clon de farmacosemiotics, medsemiotics (su sitio publicado "
    f"{SITIO_MED}/ o un clon) o clon de medsemiotics-copilot"
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config",
        default=str(RAIZ / "podcast.yml"),
        help="podcast.yml del que leer los episodios ya publicados",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("listar", help="temas con y sin episodio")
    pl.add_argument("--fuente", required=True, help=AYUDA_FUENTE)
    pl.add_argument("--pendientes", action="store_true", help="solo los que faltan")
    pl.set_defaults(func=cmd_listar)

    pp = sub.add_parser("preparar", help="material de un tema para NotebookLM")
    pp.add_argument("ident", help="id del tema (p. ej. SEL0003, HM6001) o su slug")
    pp.add_argument("--fuente", required=True, help=AYUDA_FUENTE)
    pp.add_argument("--salida", default=str(RAIZ / "notebooklm"))
    pp.set_defaults(func=cmd_preparar)

    args = ap.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
