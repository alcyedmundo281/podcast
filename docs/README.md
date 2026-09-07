# docs/ — raíz publicada por GitHub Pages

Contenido versionado:

- `.nojekyll` — evita que Pages intente procesar el directorio con Jekyll.
- `cover.jpg` — portada del podcast, 3000×3000 px, < 500 KB. **Falta: añadir.**
- `metrics.json` — lo escribe y commitea `metrics.yml`.
- `transcripts/` — transcripciones `.vtt` referenciadas desde `podcast.yml`.

Generado en cada build y **no versionado** (`.gitignore`):

- `feed.xml`, `index.html` — los produce `scripts/build_feed.py` a partir de
  `podcast.yml` durante el workflow, antes de desplegar.

Aquí nunca va un MP3: GitHub Pages corta en 1 GB por sitio.
