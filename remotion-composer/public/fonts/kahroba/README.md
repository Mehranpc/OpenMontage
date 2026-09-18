# Kahroba editorial runtime asset

Film Type 2.16 uses the licensed `Kahroba BL-LC` face for Persian opening hooks and editorial callouts.
The binary is intentionally not redistributed by this repository. Install a licensed local copy with:

`python scripts/install_kahroba_font.py "/path/to/Kahroba BL-LC.woff2"`

The installer verifies SHA-256 `0223838295d7fb72a6dce709d234ef433d7815f66ed83b6959ae2f838f3d6711`
and copies it to `remotion-composer/public/fonts/kahroba/Kahroba-BL-LC.woff2`.
Runtime browser loading verifies the same digest before measuring or painting text.
