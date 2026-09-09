// Browser-only font/layout prepass for persian_compose. No package installation,
// media generation or provider calls. The subsequent render uses the same code.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const require = createRequire(import.meta.url);
const composer = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) throw new Error('Usage: node prepare-persian-film-type.mjs INPUT.json OUTPUT.json');
let temporary;
let browser;
try {
  const {bundle} = require('@remotion/bundler');
  const {selectComposition, openBrowser} = require('@remotion/renderer');
  const props = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  if (props.design?.profile !== 'film-type') throw new Error('This prepass is only for the explicit film-type profile.');
  temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'openmontage-film-type-'));
  // Metadata measurement does not decode footage. Copy ONLY the unchanged fonts,
  // rather than duplicating every staged clip into a second temporary bundle.
  // This publicDir is for the prepass, never an override on the final render.
  const publicDir = path.join(temporary, 'public');
  fs.mkdirSync(publicDir);
  fs.cpSync(path.join(composer, 'public', 'fonts'), path.join(publicDir, 'fonts'), {recursive: true});
  const serveUrl = await bundle({
    entryPoint: path.join(composer, 'src', 'persian', 'filmType', 'prepare-entry.tsx'),
    rootDir: composer, outDir: path.join(temporary, 'bundle'), publicDir,
    enableCaching: false, gitSource: null,
  });
  const executable = process.env.REMOTION_BROWSER_EXECUTABLE;
  browser = await openBrowser('chrome', executable ? {browserExecutable: executable, logLevel: 'error'} : {logLevel: 'error'});
  const composition = await selectComposition({
    serveUrl, id: 'PersianFilmTypePrepare', inputProps: props,
    puppeteerInstance: browser, timeoutInMilliseconds: 60000, logLevel: 'error',
  });
  if (!composition.props?.filmType?.inputHash) throw new Error('The real metadata prepass returned no measured layout.');
  fs.writeFileSync(outputPath, JSON.stringify(composition.props));
} catch (error) {
  console.error("OPENMONTAGE_PREPASS_ERROR=" + JSON.stringify({message: error?.message ?? String(error)}));
  console.error(error?.stack ?? String(error));
  process.exitCode = 1;
} finally {
  // This is our own Remotion worker, not a shared/user browser.
  if (browser) { try { await browser.close({silent: true}); } catch (cleanupError) { console.error("PREPASS_CLEANUP_WARNING", cleanupError?.message ?? String(cleanupError)); } }
  if (temporary) fs.rmSync(temporary, {recursive: true, force: true});
}
