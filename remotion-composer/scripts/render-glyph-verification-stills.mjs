// Lossless verification stills for Film Type glyph order (#252).
// For each requested {momentId, frame}, renders two PNGs from the SAME prepared props:
// the delivery frame, and the same frame with only the glyphs hidden. Their difference
// is the painted ink, free of H.264 loss. Uses the project's staged public dir as-is.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const composer = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [propsPath, requestPath, outDir] = process.argv.slice(2);
if (!propsPath || !requestPath || !outDir) throw new Error('Usage: node render-glyph-verification-stills.mjs PROPS.json REQUEST.json OUT_DIR');
let temporary; let browser;
try {
  const {bundle} = require('@remotion/bundler');
  const {selectComposition, renderStill, openBrowser} = require('@remotion/renderer');
  const props = JSON.parse(fs.readFileSync(propsPath, 'utf8'));
  const request = JSON.parse(fs.readFileSync(requestPath, 'utf8'));
  if (props.design?.profile !== 'film-type' || !props.filmType?.inputHash) throw new Error('Glyph verification needs prepared Film Type props.');
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'openmontage-glyph-verify-'));
  const serveUrl = await bundle({
    entryPoint: path.join(composer, 'src', 'index.tsx'), rootDir: composer,
    outDir: path.join(temporary, 'bundle'), publicDir: path.join(composer, 'public'),
    enableCaching: false, gitSource: null,
  });
  const executable = process.env.REMOTION_BROWSER_EXECUTABLE;
  browser = await openBrowser('chrome', executable ? {browserExecutable: executable, logLevel: 'error'} : {logLevel: 'error'});
  const id = props.format === 'landscape' ? 'PersianFootageLandscape' : 'PersianFootageVertical';
  fs.mkdirSync(outDir, {recursive: true});
  const results = [];
  for (const variant of [false, true]) {
    const inputProps = {...props, verificationHideGlyphs: variant};
    const composition = await selectComposition({serveUrl, id, inputProps, puppeteerInstance: browser, timeoutInMilliseconds: 120000, logLevel: 'error'});
    for (const item of request.frames) {
      const output = path.join(outDir, `${item.momentId}-${variant ? 'background' : 'frame'}.png`);
      await renderStill({serveUrl, composition, inputProps: composition.props, frame: item.frame, output, imageFormat: 'png', puppeteerInstance: browser, timeoutInMilliseconds: 120000, logLevel: 'error'});
      results.push({momentId: item.momentId, frame: item.frame, variant: variant ? 'background' : 'frame', path: output});
    }
  }
  fs.writeFileSync(path.join(outDir, 'stills.json'), JSON.stringify({inputHash: props.filmType.inputHash, results}, null, 2));
} catch (error) {
  console.error("OPENMONTAGE_GLYPH_STILLS_ERROR=" + JSON.stringify({message: error?.message ?? String(error)}));
  process.exitCode = 1;
} finally {
  if (browser) { try { await browser.close({silent: true}); } catch {} }
  if (temporary) fs.rmSync(temporary, {recursive: true, force: true});
}
