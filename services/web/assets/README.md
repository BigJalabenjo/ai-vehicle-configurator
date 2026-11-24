# Brand assets (optional)

The web client picks these files up automatically when the web image is built. If they are
missing, the app falls back to a text wordmark and a system font, so everything works without them.

| What | Where | Accepted |
|---|---|---|
| Logo (header, shown at 32 × 32 px) | `logo.<ext>` in this folder | `.svg`, `.png`, `.webp`, `.jpg` (any name starting with `logo.`) |
| Brand font | any file in `fonts/` | `.woff2`, `.woff`, `.otf`, `.ttf` |

Font weights are read from the file names: Thin 100, Light 300, Regular 400, Medium 500,
Bold 700 (e.g. `BMWGroupTN-Light.otf`). Web formats (`.woff2`) are preferred when the same weight
exists twice, because they are much smaller.

After adding or changing files, rebuild the web container: `docker compose up --build -d web`.

The BMW logo and BMW fonts are protected brand assets. Only add them if you have the right to
use them, and check whether you may redistribute them before committing them to a public repository.
