# medsemiotics — podcast

Feed de podcast auto-hospedado dentro del ecosistema powersemiotics, sin
servicios de terceros y sin costo. Una sola fuente (`podcast.yml`) compila a
un feed RSS estático servido por GitHub Pages.

---

## La decisión de arquitectura

GitHub Pages publica sitios de **hasta 1 GB** y bloquea archivos de más de
100 MiB. Un episodio de 30 minutos en MP3 mono a 96 kbps pesa unos 22 MB: a
partir del episodio ~45 el sitio deja de desplegarse. **El audio no puede
vivir en el repositorio de Pages.**

La documentación de GitHub dice de los assets de release: *"We don't limit the
total size of the binary files in the release or the bandwidth used to deliver
them."* De ahí la separación:

| Capa | Dónde vive | Por qué |
|---|---|---|
| Fuente | `podcast.yml` | Un archivo legible, versionado, sin base de datos |
| Feed y sitio | GitHub Pages (`docs/`) | Estático, kilobytes, dentro del techo de 1 GB |
| Audio (MP3) | GitHub Releases | Sin límite de tamaño ni de ancho de banda, con CDN |
| Métricas | API de releases | `download_count` real, sin rastreadores ni cookies |
| Archivo y DOI | Zenodo (opcional) | Convierte cada episodio en objeto citable |

El sitio publicado no hace ninguna llamada a servicios externos en tiempo de
ejecución. Es XML y HTML estáticos: nada que se apague solo.

---

## Puesta en marcha

1. **Crear el repositorio** con el nombre `podcast`, de modo que Pages lo
   sirva en `powersemiotics.com/podcast/`. Si eliges otro nombre, ajusta
   `show.base_url` en `podcast.yml`; ese valor y la ruta real deben coincidir
   o el `<atom:link rel="self">` quedará mal y los directorios rechazarán el
   feed.

2. **Ajustar `podcast.yml`**: `show.audio_repo` debe apuntar a este mismo
   repositorio (`alcyedmundo281/podcast`).

3. **Portada**: colocar `docs/cover.jpg`, cuadrada de 3000×3000 px, por
   debajo de 500 KB. Apple rechaza feeds con portadas menores de 1400 px.

4. **Activar Pages**: *Settings → Pages → Source: GitHub Actions*.

5. **Publicar el primer episodio** (ver abajo).

6. **Enviar el feed una sola vez** a Apple Podcasts Connect, Spotify for
   Podcasters, YouTube Music y Podcast Index. A partir de ahí todos consultan
   el feed por su cuenta.

---

## Publicar un episodio

```bash
# 1. Normalizar el audio a -19 LUFS (mono, voz) y codificar a 96 kbps
ffmpeg -i crudo.wav -af loudnorm=I=-19:TP=-1.5:LRA=11 \
       -ac 1 -b:a 96k -codec:a libmp3lame ep004.mp3

# 2. Crear el release con el MP3 como asset. El tag es lo que enlaza
#    el episodio con su audio: debe coincidir con `tag:` en podcast.yml.
gh release create ep004 ep004.mp3 \
   --title "Episodio 4" \
   --notes "Audio del episodio 4 de medsemiotics."

# 3. Añadir la entrada en podcast.yml y hacer push.
#    El workflow resuelve la URL y el tamaño en bytes por sí solo.
git add podcast.yml && git commit -m "ep004" && git push
```

No se escribe a mano ningún tamaño de archivo ni ninguna URL de descarga:
`build_feed.py` los toma de la API de releases en cada compilación.

---

## Scripts

| Script | Qué hace |
|---|---|
| `scripts/build_feed.py` | `podcast.yml` → `docs/feed.xml` + `docs/index.html` |
| `scripts/validate_feed.py` | Puerta de calidad previa al despliegue |
| `scripts/metrics.py` | Descargas por episodio + serie temporal propia |

```bash
pip install -r requirements.txt

python3 scripts/build_feed.py               # consulta la API de releases
python3 scripts/build_feed.py --offline     # usa size_bytes de podcast.yml
python3 scripts/validate_feed.py docs/feed.xml
python3 scripts/metrics.py --dry-run
```

La única dependencia de construcción es PyYAML, fijada en `requirements.txt`.
El sitio publicado no depende de nada.

---

## Qué verifica el validador

Lo que rompe una suscripción sin dar aviso:

- XML mal formado.
- **GUID duplicado o cambiado.** El GUID deriva del `slug`. Cambiar un slug
  ya publicado hace que los clientes vuelvan a descargar el episodio como si
  fuera nuevo. Los slugs no se tocan nunca.
- `<enclosure>` que responde 404, o cuyo `length` no coincide con el tamaño
  real del archivo — la causa más común de reproducción cortada.
- `pubDate` fuera de RFC 2822 o sin zona horaria.
- Ausencia de `itunes:category`, `itunes:image` o `itunes:owner/email`, que
  son motivo de rechazo en Apple.

---

## Métricas sin rastreadores

`download_count` de la API de releases es el número real de descargas del
MP3: la misma magnitud que miden los prefijos comerciales, obtenida sin
redirecciones, sin cookies y sin exponer a los oyentes.

GitHub sólo expone el acumulado, así que `metrics.py` guarda una muestra
diaria en `data/metrics-history.json` y publica el estado actual con sus
incrementos en `docs/metrics.json`, listo para que el sitio lo consuma.

---

## Portabilidad

El feed vive en un dominio propio (`powersemiotics.com/podcast/feed.xml`).
Migrar a cualquier otro proveedor es poner una redirección 301 en esa URL:
ningún suscriptor se pierde. `<podcast:guid>` conserva además la identidad
del programa aunque la URL cambie.

---

## Capa opcional: DOI por episodio

Depositar cada MP3 en Zenodo (hasta 50 GB y 100 archivos por registro) le da
a cada episodio un DOI y lo vuelve citable, coherente con el resto de
medsemiotics. Úsese como archivo y citabilidad, **no** como URL del
`<enclosure>`: Zenodo no está pensado para el sondeo constante de los
clientes de podcast, y su ventana de modificación de archivos se cierra a los
45 días de publicar.

---

## Licencia

Contenido bajo CC BY-SA 4.0.
