#!/usr/bin/env python3
"""
transcribir.py — transcripción de un episodio con Whisper, en local.

Transcribe el MP3 masterizado —el mismo que oyen los suscriptores, para que
los tiempos coincidan— con faster-whisper `large-v3` y escribe las dos
salidas que el repositorio publica:

  docs/transcripts/epNNN.vtt   WebVTT; el feed la enlaza como
                               <podcast:transcript>
  docs/transcripts/epNNN.md    la misma transcripción en párrafos, para leer

La salida es un BORRADOR. La norma de revisión está en CLAUDE.md: se corrigen
terminología y errores evidentes de transcripción, nunca lo que dijeron los
presentadores. Por eso el script no sobrescribe una transcripción existente
sin --forzar: pisaría las correcciones hechas a mano.

Con --fuente, los términos de la fuente curada (DCI, clases, título) van a
Whisper como hotwords —reconoce mejor «hidroclorotiazida» si la ha
visto escrita— y al terminar se listan los que no aparecen en la
transcripción: son los primeros candidatos a revisar.

La dependencia es opcional y pesada (modelo de ~3 GB, CUDA). No está en el
grupo `dev`, así que CI no la instala:

  uv sync --group transcripcion

Uso:
  uv run --group transcripcion python scripts/transcribir.py \\
      notebooklm/<slug>/ep004.mp3 --numero 4 --titulo "..." \\
      --fuente notebooklm/<slug>/fuente.md
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Protocol

MODELO = "large-v3"
IDIOMA = "es"

# Corte de los cues del VTT. Los episodios publicados usan cues de 3 a 4 s:
# una o dos líneas cortas, legibles en cualquier reproductor.
CUE_MAX_SEG = 4.5
CUE_MAX_CHARS = 84
CUE_MIN_SEG_EN_PUNTO = 1.5

FIN_DE_FRASE = (".", "?", "!", "…")

# Párrafos del Markdown: se parte en una pausa o cuando el párrafo se alarga.
PARRAFO_PAUSA_SEG = 0.8
PARRAFO_MAX_CHARS = 600

AVISO = (
    "Generada automáticamente y corregida en terminología clínica.",
    "Puede contener errores; la fuente autorizada es el audio.",
)


# --------------------------------------------------------------------------- #
#  faster-whisper no publica tipos. En vez de relajar mypy, se carga con
#  importlib y se describe sólo la superficie que se usa.
# --------------------------------------------------------------------------- #


class Palabra(Protocol):
    start: float
    end: float
    word: str


class Segmento(Protocol):
    start: float
    end: float
    text: str
    words: list[Palabra] | None


class Info(Protocol):
    duration: float
    language: str


class Modelo(Protocol):
    def transcribe(
        self, audio: str, **opciones: object
    ) -> tuple[Iterable[Segmento], Info]: ...


@dataclass
class Cue:
    inicio: float
    fin: float
    texto: str


def morir(msg: str) -> NoReturn:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def habilitar_cuda_windows() -> None:
    """Las DLL de cuBLAS y cuDNN vienen de los wheels nvidia-*; Windows no las
    busca en site-packages por su cuenta.

    Hacen falta las dos vías: add_dll_directory cubre las dependencias al
    importar, pero ctranslate2 carga cuBLAS en diferido con LoadLibrary, que
    sólo mira el PATH."""
    if sys.platform == "win32":
        nvidia = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
        carpetas = [str(c) for c in nvidia.glob("*/bin")]
        for carpeta in carpetas:
            os.add_dll_directory(carpeta)
        os.environ["PATH"] = os.pathsep.join([*carpetas, os.environ.get("PATH", "")])


def cargar_modelo(dispositivo: str) -> Modelo:
    habilitar_cuda_windows()
    try:
        fw = importlib.import_module("faster_whisper")
    except ModuleNotFoundError:
        morir("falta faster-whisper: uv sync --group transcripcion")
    tipo = "float16" if dispositivo == "cuda" else "int8"
    modelo: Modelo = fw.WhisperModel(MODELO, device=dispositivo, compute_type=tipo)
    return modelo


# --------------------------------------------------------------------------- #
#  Glosario desde la fuente curada
# --------------------------------------------------------------------------- #


def terminos_de(fuente: Path) -> list[str]:
    """Título, DCI y clases de la fuente.md que escribe temas.py."""
    texto = fuente.read_text(encoding="utf-8")
    terminos: list[str] = []
    titulo = re.search(r"^# (.+)$", texto, re.MULTILINE)
    if titulo:
        terminos.append(titulo.group(1).strip())
    for clave in ("Dci", "Clase"):
        for m in re.finditer(rf"^- \*\*{clave}:\*\* (.+)$", texto, re.MULTILINE):
            valor = m.group(1).strip()
            if valor not in terminos:
                terminos.append(valor)
    return terminos


# Lo que Whisper destroza si no lo ha visto escrito: el nombre del proyecto, y
# siglas que se pronuncian como palabra («IECA», no «IGA»).
GLOSARIO_FIJO = ("farmacosemiotics", "medsemiotics", "IECA", "ARA-II", "EVC", "PMID")

# Sufijos de DCI: capta los fármacos que la fuente nombra de pasada —el
# comparador de un ensayo, el representante de clase— y no son candidatos.
SUFIJOS_DCI = r"(?:pril|sartán|dipino|tiazida|talidona|olol|idona|mab|nib|statina)"


def vocabulario_de(fuente: Path) -> list[str]:
    """Vocabulario para el prompt de Whisper: id del tema, siglas y fármacos
    citados en el texto, además del glosario fijo."""
    # Sin las consultas de PubMed: sus operadores (AND, OR) no son vocabulario.
    texto = "\n".join(
        linea
        for linea in fuente.read_text(encoding="utf-8").splitlines()
        if not linea.startswith("- **Consulta:**")
    )
    vistos: list[str] = []

    def sumar(t: str) -> None:
        if t.casefold() not in (v.casefold() for v in vistos):
            vistos.append(t)

    ident = re.search(r"farmacosemiotics \((\w+)\)", texto)
    if ident:
        sumar(ident.group(1))
    # Sólo letras: deja fuera los códigos ATC y CIE (C03AA03, BA00).
    for sigla in re.findall(r"\b[A-Z]{3,}(?:-[A-Z]+)*\b", texto):
        sumar(sigla)
    for farmaco in re.findall(rf"\b[a-záéíóú]+{SUFIJOS_DCI}\b", texto):
        sumar(farmaco)
    for t in GLOSARIO_FIJO:
        sumar(t)
    return vistos


def prompt_inicial(terminos: Sequence[str]) -> str | None:
    # Whisper sólo mira ~224 tokens de prompt; mejor corto y denso.
    return ", ".join(terminos)[:600] + "." if terminos else None


def ausentes(terminos: Sequence[str], transcripcion: str) -> list[str]:
    plano = transcripcion.casefold()
    return [t for t in terminos if t.casefold() not in plano]


# --------------------------------------------------------------------------- #
#  Segmentos de Whisper -> cues -> VTT y Markdown
# --------------------------------------------------------------------------- #


def a_cues(segmentos: Iterable[Segmento]) -> list[Cue]:
    cues: list[Cue] = []
    actual: list[Palabra] = []

    def cerrar() -> None:
        texto = "".join(p.word for p in actual).strip()
        if texto:
            cues.append(Cue(actual[0].start, actual[-1].end, texto))
        actual.clear()

    for seg in segmentos:
        for i, palabra in enumerate(seg.words or []):
            # Whisper marca con un espacio inicial la palabra que empieza; sin
            # él es continuación de la anterior («11» + «,5%»). Ahí no se
            # corta nunca, ni siquiera entre segmentos: saldría «11 ,5%».
            continua = not palabra.word.startswith(" ")
            if actual and not continua:
                dur = palabra.end - actual[0].start
                largo = len("".join(p.word for p in actual)) + len(palabra.word)
                if i == 0 or dur > CUE_MAX_SEG or largo > CUE_MAX_CHARS:
                    cerrar()
            actual.append(palabra)
            fin_de_frase = palabra.word.rstrip().endswith(FIN_DE_FRASE)
            if fin_de_frase and palabra.end - actual[0].start >= CUE_MIN_SEG_EN_PUNTO:
                cerrar()
    if actual:
        cerrar()
    return cues


def marca(segundos: float) -> str:
    ms = round(segundos * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def duracion_corta(segundos: float) -> str:
    total = round(segundos)
    h, resto = divmod(total, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_vtt(cues: Sequence[Cue], numero: int, titulo: str) -> str:
    lineas = [
        "WEBVTT",
        "",
        "NOTE",
        f"Transcripción del episodio {numero} de medsemiotics — {titulo}.",
        *AVISO,
        "",
    ]
    for i, cue in enumerate(cues, start=1):
        lineas += [str(i), f"{marca(cue.inicio)} --> {marca(cue.fin)}", cue.texto, ""]
    return "\n".join(lineas)


def parrafos(cues: Sequence[Cue]) -> list[str]:
    salida: list[str] = []
    actual: list[str] = []
    fin_previo: float | None = None
    for cue in cues:
        pausa = fin_previo is not None and cue.inicio - fin_previo >= PARRAFO_PAUSA_SEG
        largo = sum(len(t) + 1 for t in actual)
        # Por largo sólo se parte al final de una frase: un párrafo que acaba
        # en «con fracción» y sigue en «de eyección reducida» no se lee.
        cierra_frase = bool(actual) and actual[-1].endswith(FIN_DE_FRASE)
        if actual and cierra_frase and (pausa or largo > PARRAFO_MAX_CHARS):
            salida.append(" ".join(actual))
            actual = []
        actual.append(cue.texto)
        fin_previo = cue.fin
    if actual:
        salida.append(" ".join(actual))
    return salida


def render_md(
    cues: Sequence[Cue], numero: int, titulo: str, titulo_largo: str, dur: float
) -> str:
    cabecera = [
        f"# {titulo_largo}",
        "",
        f"Transcripción del episodio {numero} de **medsemiotics**. {duracion_corta(dur)}.",
        "",
        "> Generada automáticamente desde el audio y corregida en terminología",
        "> clínica. Puede contener errores; la fuente autorizada es el audio.",
        "",
        "---",
        "",
    ]
    cuerpo = "\n\n".join(parrafos(cues))
    return "\n".join(cabecera) + "\n" + cuerpo + "\n"


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0] if __doc__ else None
    )
    ap.add_argument("audio", type=Path, help="MP3 masterizado del episodio")
    ap.add_argument("--numero", type=int, required=True, help="número de episodio")
    ap.add_argument(
        "--titulo",
        required=True,
        help="título del episodio, como irá en podcast.yml",
    )
    ap.add_argument(
        "--tema",
        help="nombre corto para la NOTE del VTT (por defecto, el título)",
    )
    ap.add_argument("--fuente", type=Path, help="fuente.md del tema (glosario)")
    ap.add_argument("--out", type=Path, default=Path("docs/transcripts"))
    ap.add_argument("--dispositivo", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument(
        "--forzar",
        action="store_true",
        help="sobrescribir una transcripción existente (pierde las correcciones)",
    )
    args = ap.parse_args()

    audio: Path = args.audio
    if not audio.is_file():
        morir(f"no existe el audio: {audio}")
    vtt = args.out / f"ep{args.numero:03d}.vtt"
    md = args.out / f"ep{args.numero:03d}.md"
    existentes = [p for p in (vtt, md) if p.exists()]
    if existentes and not args.forzar:
        morir(
            f"ya existe {', '.join(map(str, existentes))}. Puede llevar "
            "correcciones a mano; usa --forzar si de verdad quieres pisarlo."
        )

    terminos = terminos_de(args.fuente) if args.fuente else []
    vocabulario = vocabulario_de(args.fuente) if args.fuente else []
    modelo = cargar_modelo(args.dispositivo)
    print(f"transcribiendo {audio} con {MODELO} en {args.dispositivo}…")
    segmentos, info = modelo.transcribe(
        str(audio),
        language=IDIOMA,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
        # hotwords y no initial_prompt: sin condition_on_previous_text, el
        # prompt inicial sólo llega a la primera ventana de 30 s; hotwords se
        # antepone a todas.
        hotwords=prompt_inicial([*terminos, *vocabulario]),
    )
    cues = a_cues(segmentos)
    if not cues:
        morir("Whisper no devolvió texto")

    tema = args.tema or args.titulo
    args.out.mkdir(parents=True, exist_ok=True)
    # newline="\n": en Windows write_text traduciría a CRLF por su cuenta.
    vtt.write_text(render_vtt(cues, args.numero, tema), encoding="utf-8", newline="\n")
    md.write_text(
        render_md(cues, args.numero, tema, args.titulo, info.duration),
        encoding="utf-8",
        newline="\n",
    )
    print(f"  {vtt}  {len(cues)} cues")
    print(f"  {md}  {duracion_corta(info.duration)}")

    faltan = ausentes(terminos, " ".join(c.texto for c in cues))
    if faltan:
        print("\nTérminos de la fuente que no aparecen tal cual (revisar):")
        for t in faltan:
            print(f"  - {t}")
    print("\nEs un borrador: revísalo según la norma de CLAUDE.md antes de publicar.")


if __name__ == "__main__":
    main()
