# medsemiotics — podcast

Feed de podcast estático. Una sola fuente (`podcast.yml`) compila a RSS servido
por GitHub Pages. El audio vive en GitHub Releases, nunca en el repositorio.

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

El paso 3 es el que despliega. El evento `release` corre sobre el tag y el
entorno `github-pages` restringe los despliegues a la rama por defecto, así que
ese run falla en `deploy` salvo que se añada una regla para tags `ep*`.
