# medsemiotics — podcast

Feed de podcast estático. Una sola fuente (`podcast.yml`) compila a RSS servido
por GitHub Pages. El audio vive en GitHub Releases, nunca en el repositorio.

## Una sola vez, al clonar

```bash
uv sync --frozen
uv run pre-commit install
```

A partir de ahí las puertas corren solas en cada `git commit`. No hay que
acordarse de nada: si el commit pasa, el push pasa.

Los hooks son `local` y llaman a `uv run` a propósito, de modo que ruff y mypy
salen de `uv.lock` — las mismas versiones que usa CI. Los mirrors oficiales de
pre-commit fijan su propia versión y se desincronizan en silencio: entonces el
commit pasa y el push falla, que es justo lo que esto evita.

Además de las tres puertas, dos guardas de dominio que no se pueden razonar
desde el código:

- **`sin-audio`** — ningún `.mp3` entra al repositorio, ni con `git add -f`.
- **`slugs-estables`** — compara los slugs del índice contra HEAD y falla si
  desaparece alguno. Renombrar un slug publicado es irreversible desde el feed.

Ambas se saltan con `git commit --no-verify` cuando de verdad toca (por ejemplo,
un episodio que nunca llegó a publicarse). Que haya que escribirlo a mano es el
punto: obliga a decidirlo, no a olvidarlo.

## Antes de dar por terminado cualquier cambio en `scripts/`

Estas tres puertas son obligatorias y se ejecutan en este orden. No propongas
un cambio sin haberlas pasado:

```bash
uv sync --frozen
uv run ruff format scripts/
uv run ruff check --fix scripts/
uv run mypy
```

`mypy` corre en modo `strict`. No lo relajes, no añadas `# type: ignore` y no
metas excepciones en `pyproject.toml` para hacer pasar un cambio: el código son
tres archivos pequeños y cualquier error de tipos ahí es un error real. Si algo
no tipa, el arreglo es el código.

Después, la prueba funcional:

```bash
# build con tamaños simulados, sin tocar la API de releases
uv run python scripts/build_feed.py --config <copia con size_bytes> --out /tmp/x --offline
uv run python scripts/validate_feed.py /tmp/x/feed.xml --skip-network
```

## Reglas del dominio que no son obvias

- **Los `slug` de episodio no se cambian nunca.** El GUID del feed deriva del
  slug. Cambiarlo hace que todos los suscriptores vuelvan a descargar el
  episodio como si fuera nuevo. `build_feed.py` aborta ante slugs duplicados;
  no hay defensa contra renombrar uno ya publicado salvo no hacerlo.
- **Nunca escribas a mano el tamaño de un enclosure.** `size_bytes` existe solo
  para builds `--offline`. En producción el tamaño lo resuelve la API de
  releases, porque un MP3 puede ganar bytes al pasar por cualquier pipeline que
  toque metadatos ID3, y un `length` desfasado corta la reproducción.
- **Ningún `.mp3` entra al repositorio.** GitHub Pages corta en 1 GB por sitio;
  los assets de release no tienen límite de tamaño ni de ancho de banda. El
  `.gitignore` los excluye a propósito.
- **`docs/feed.xml` y `docs/index.html` son salida generada** y están en
  `.gitignore`. `docs/metrics.json` sí se versiona: lo commitea `metrics.yml`.
- **Las fechas llevan zona horaria.** `pub_date` es ISO 8601 con `-05:00`. Una
  fecha futura hace que muchos clientes oculten el episodio.

## Separación de los workflows

- `quality.yml` vigila el **código**: ruff, mypy, prueba de humo del generador.
- `build-feed.yml` vigila el **feed**: compila, valida contra el asset real y
  despliega.

Están separados a propósito. Un fallo de estilo no debe impedir publicar un
episodio, y una publicación urgente no debe tentar a saltarse el linter.

## Publicar un episodio

1. Masterizar: mono, 96 kbps, −19 LUFS, pico real bajo −1,5 dBTP.
2. `gh release create epNNN epNNN.mp3 --target main --title "..."`.
3. Añadir la entrada en `podcast.yml` y hacer push a `main`.

El paso 3 es el que despliega, y el orden importa: `build_feed.py` resuelve el
tamaño del enclosure contra la API de releases, así que sin el release del paso
2 el build falla.

`build-feed.yml` no escucha el evento `release` a propósito: ese run publicaría
un feed que aún no contiene el episodio, y además fallaría en `deploy` porque
corre sobre el tag y el entorno `github-pages` solo admite despliegues desde la
rama por defecto.

Si alguna vez reemplazas el MP3 de un release ya publicado, su tamaño en bytes
cambia y el feed queda desfasado sin que `podcast.yml` se haya tocado. Ese es
el caso de `workflow_dispatch`: *Actions → build feed → Run workflow*.
