/** #387 v3: backdrop-adaptive text shadow.
 *
 * `lib/persian_backdrop_luma.py` samples the footage under each placed text block and
 * stores a multiplier per moment and shot: above 1 on a bright backdrop, below 1 on a
 * dark one. Anything missing or invalid keeps the profile strength (1).
 */
export type FilmTypeBackdrop = {
  readonly version: string;
  readonly moments: Readonly<Record<string, Readonly<Record<string, {readonly multiplier: number; readonly luma?: number; readonly samples?: number; readonly error?: string}>>>>;
};

export const backdropMultiplier = (backdrop: FilmTypeBackdrop | undefined, momentId: string, shotId: string | undefined): number => {
  const value = shotId === undefined ? undefined : backdrop?.moments?.[momentId]?.[shotId]?.multiplier;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 1;
};
