/**
 * Estedad font loading for the Persian composition.
 *
 * Uses the platform `FontFace` API rather than `@remotion/fonts`, for two
 * reasons: `@remotion/fonts` is not among the installed `@remotion/*` packages
 * (adding it would touch shared `package.json` for no capability gain), and the
 * raw API is what lets the promise be shared with the measurement layer.
 *
 * ## The ordering rule this file exists to enforce
 *
 * Layout here is computed from real glyph widths via canvas `measureText`. A
 * canvas measures with whatever font is *currently* registered: ask before
 * Estedad has loaded and the browser silently substitutes a fallback, returns
 * its widths, and the fitter commits line breaks computed for the wrong
 * typeface. Nothing errors. The render simply comes out with text that overflows
 * its panel or is mysteriously shrunk, and only on some runs, because whether
 * the font wins the race depends on disk cache state.
 *
 * So: **await `estedadReady` before any `measureText` call.** `measurePersian`
 * enforces it by throwing rather than trusting callers to remember.
 *
 * The `delayRender` handle is created at module scope but *continued inside a
 * `.then`*, so the handle is always cleared. A `delayRender` that can only be
 * continued by a React effect deadlocks if the component never mounts, which
 * surfaces as an unexplained render timeout.
 */

import { continueRender, delayRender, staticFile } from "remotion";

export type EstedadWeight = 500 | 700 | 900;

/** Weight → vendored file. Only real weights, so Chrome never fakes a bold. */
const WEIGHT_FILES: Record<EstedadWeight, string> = {
  500: "fonts/estedad/Estedad-Medium.ttf",
  700: "fonts/estedad/Estedad-Bold.ttf",
  900: "fonts/estedad/Estedad-Black.ttf",
};

/**
 * The one family name to use everywhere.
 *
 * All three weights register under this single family so the browser resolves a
 * `fontWeight` to a real file instead of synthesizing. Never write a CSS
 * fallback chain after it: a fallback that silently engages is exactly the
 * failure this module prevents, and a missing font should be a loud error.
 */
export const ESTEDAD_FAMILY = "Estedad";

/** Private licensed display face used only by Film Type 2.16+ editorial moments. */
export const KAHROBA_FAMILY = "KahrobaEditorial";
export const KAHROBA_ASSET_PATH = "fonts/kahroba/Kahroba-BL-LC.woff2";

let kahrobaLoaded = false;
let kahrobaPromise: Promise<void> | null = null;

const bytesSha256 = async (bytes: ArrayBuffer): Promise<string> =>
  [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");

export function ensureKahrobaReady(expectedSha256: string): Promise<void> {
  if (kahrobaLoaded) return Promise.resolve();
  if (kahrobaPromise) return kahrobaPromise;
  const handle = delayRender("Loading licensed Kahroba editorial typeface");
  kahrobaPromise = (async () => {
    const response = await fetch(staticFile(KAHROBA_ASSET_PATH));
    if (!response.ok) {
      throw new Error(`Kahroba asset is missing (${response.status}); run scripts/install_kahroba_font.py with the licensed BL-LC source.`);
    }
    const bytes = await response.arrayBuffer();
    const actualSha256 = await bytesSha256(bytes);
    if (actualSha256 !== expectedSha256.toLowerCase()) {
      throw new Error(`Kahroba asset SHA-256 mismatch: ${actualSha256}`);
    }
    const face = new FontFace(KAHROBA_FAMILY, bytes, {weight: "900", style: "normal", display: "block"});
    const loaded = await face.load();
    document.fonts.add(loaded);
    await document.fonts.load(`900 120px "${KAHROBA_FAMILY}"`, "بازی");
    kahrobaLoaded = true;
  })();
  kahrobaPromise.then(
    () => continueRender(handle),
    (error) => { continueRender(handle); throw error; },
  );
  return kahrobaPromise;
}

export function isKahrobaLoaded(): boolean {
  return kahrobaLoaded;
}

const handle = delayRender("Loading Estedad (Persian typeface)");

/**
 * Resolves once every weight is registered and measurable.
 *
 * Rejects if any weight fails. That is deliberate: a Persian render with a
 * missing weight would fall back mid-layout, and a broken frame that looks
 * plausible is worse than a failed render with a clear message.
 */
export const estedadReady: Promise<void> = (async () => {
  const faces = (Object.entries(WEIGHT_FILES) as Array<[string, string]>).map(
    ([weight, path]) => {
      const face = new FontFace(
        ESTEDAD_FAMILY,
        `url(${staticFile(path)}) format("truetype")`,
        { weight: String(weight), style: "normal", display: "block" },
      );
      return face.load().then((loaded) => {
        document.fonts.add(loaded);
      });
    },
  );

  await Promise.all(faces);

  // `document.fonts.load` forces the font to be resolved for this exact
  // family/weight/size string. Without it, `document.fonts.check` can report
  // false for a face that is registered but not yet realized, and the first
  // `measureText` would race the realization.
  await Promise.all(
    (Object.keys(WEIGHT_FILES) as Array<string>).map((weight) =>
      document.fonts.load(`${weight} 100px "${ESTEDAD_FAMILY}"`, "الف"),
    ),
  );
})();

let fontsLoaded = false;

estedadReady.then(
  () => {
    fontsLoaded = true;
    continueRender(handle);
  },
  (error) => {
    // Continue the handle before surfacing the failure, otherwise the render
    // hangs to its timeout and reports "delayRender timed out" instead of the
    // real cause.
    continueRender(handle);
    throw new Error(
      `Estedad failed to load — Persian layout cannot be measured: ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  },
);

/** True once every weight is registered. Cheap enough for a render guard. */
export function isEstedadLoaded(): boolean {
  return fontsLoaded;
}

/** The `font` shorthand for a canvas context, in the exact form CSS expects. */
export function estedadCanvasFont(
  fontSizePx: number,
  weight: EstedadWeight,
): string {
  return `${weight} ${fontSizePx}px "${ESTEDAD_FAMILY}"`;
}
