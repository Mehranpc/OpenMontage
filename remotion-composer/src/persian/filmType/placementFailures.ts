/**
 * Collecting placement refusals instead of stopping at the first.
 *
 * A placement collision is a property of one moment's frame geometry, so several moments
 * can fail independently and for different reasons. Stopping at the first makes a draft
 * with three bad moments indistinguishable from one with a single bad moment, so every
 * repair cycle costs a full round: the L3 run this came from spent four cycles
 * discovering four collisions one at a time (#164).
 *
 * The *collection* itself is four lines of try/catch in the moment loop, which needs a
 * browser to exercise at all; these are the decisions worth pinning, and they are what the
 * render path calls.
 *
 * Deliberately dependency-free so they can be exercised directly under `node
 * --experimental-strip-types`, with no build step and no test framework.
 */

export type PlacementFailure = { id: string; error: unknown };

const DIAGNOSTICS_MARKER = "OPENMONTAGE_DIAGNOSTICS=";

/**
 * A failure's message with its machine-readable diagnostics suffix removed.
 *
 * Only one `OPENMONTAGE_DIAGNOSTICS=` payload may survive into a combined message: the
 * workflow splits on the *first* marker and parses everything after it, so a second one
 * would corrupt the parse and lose the recovery class.
 */
export function messageWithoutDiagnostics(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  const at = text.indexOf(DIAGNOSTICS_MARKER);
  return (at === -1 ? text : text.slice(0, at)).trim();
}

/**
 * The message for a set of failures.
 *
 * With one failure this is that failure's own message, byte for byte, so existing callers
 * and diagnostics parsing see exactly what they saw before. With several, the first keeps
 * its diagnostic payload and the rest follow as readable lines naming their moments.
 */
export function placementFailureMessage(failures: ReadonlyArray<PlacementFailure>): string {
  if (!failures.length) return "";
  const first = failures[0].error instanceof Error
    ? failures[0].error.message
    : String(failures[0].error);
  if (failures.length === 1) return first;
  const rest = failures
    .slice(1)
    .map((failure) => `  - ${failure.id}: ${messageWithoutDiagnostics(failure.error)}`)
    .join("\n");
  return (
    `${first}\n\nFilm Type placement refused for ${failures.length} moments in one pass. ` +
    `One repair cycle can address all of them; the rest are:\n${rest}`
  );
}
