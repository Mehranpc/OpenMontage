# Kahroba editorial runtime asset

Film Type 2.16 uses the licensed `Kahroba EB-LC` face for Persian opening hooks and editorial callouts.
The binary is intentionally not redistributed by this repository. Install a licensed local copy with:

`python scripts/install_kahroba_font.py "/path/to/Kahroba EB-LC.woff2"`

The installer verifies SHA-256 `354d3f6fd8f3a330a766d403beac0a37d3d7378a754067265d766ee1a1cae14d`
and copies it to `remotion-composer/public/fonts/kahroba/Kahroba-EB-LC.woff2`.
Runtime browser loading verifies the same digest before measuring or painting text.
