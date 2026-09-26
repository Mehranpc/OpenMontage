/**
 * Check for `src/persian/filmType/placementFailures.ts` (#164).
 *
 * Run with: node --experimental-strip-types tests/placement-failures.test.mjs
 *
 * The helper is deliberately dependency-free so the collection semantics -- the part that
 * can silently regress while every render still passes -- are exercised directly. Without
 * a check here, "report every infeasible moment" would be an unverifiable change to a
 * rendered-path module.
 */
import assert from "node:assert/strict";

import {
  messageWithoutDiagnostics,
  placementFailureMessage,
} from "../src/persian/filmType/placementFailures.ts";

const MARKER = "OPENMONTAGE_DIAGNOSTICS=";

// A single failure keeps its own message byte for byte, so existing callers and the
// workflow's diagnostics parsing see exactly what they saw before.
const only = placementFailureMessage([{ id: "m-2", error: new Error("boom") }]);
assert.equal(only, "boom");

// --- only one diagnostics payload may survive ----------------------------------------

const withPayload = `Moment m-2: refused. ${MARKER}{"code":"ASSET_SELECTION_HARD_REGION_COLLISION"}`;
assert.equal(
  messageWithoutDiagnostics(new Error(withPayload)),
  "Moment m-2: refused.",
  "the marker and everything after it must be stripped",
);

const combined = placementFailureMessage([
  { id: "m-2", error: new Error(withPayload) },
  { id: "m-3", error: new Error(`Moment m-3: refused. ${MARKER}{"code":"FILM_TYPE_PREPASS"}`) },
]);

assert.equal(
  combined.split(MARKER).length - 1,
  1,
  "exactly one diagnostics payload may survive, or the workflow's parser loses the class",
);
assert.ok(combined.includes("m-2: refused."), "the first failure keeps its own message");
assert.ok(combined.includes("m-3: refused."), "the remaining failures are named");
assert.ok(combined.includes("2 moments"), "the count is stated");

// --- the empty case is not a message --------------------------------------------------

assert.equal(placementFailureMessage([]), "");

console.log("placement-failures: ok");
