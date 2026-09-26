/** Film Type reading-time model, dependency-free so it can run outside the renderer.
 *
 * `assertFilmTiming` in `layout.ts` enforces this at render. The Python gate
 * (`lib.persian_moments.PersianMoment.film_step_requirements`) mirrors it and
 * `tests/contracts/test_issue216_film_reading_model_parity.py` runs both over one corpus,
 * so the cheap pre-render check refuses exactly what the browser refuses (#216).
 * Keep this module free of font/DOM imports: the contract test bundles it for Node.
 */
import { MOMENT_READ_CPS, MOMENT_FIXATION_SECONDS, MOMENT_BLOCK_SECONDS, MOMENT_SOURCE_READ_WEIGHT } from "../tokens";
import { visibleLength } from "../text";

type Motion = { lineDelaySeconds: number; enterSeconds: number; cutInSeconds: number; exitSeconds: number };
type Segment = { role: string; text: string; revealAfterSeconds?: number };
type TimedMoment = { startSeconds: number; endSeconds: number; segments: readonly Segment[]; presentation?: { motion?: string } };

export function filmRowDelay(row: { revealAfterSeconds: number; segmentIndex: number; role: string }, p: { motion: Pick<Motion, "lineDelaySeconds"> }): number {
  return row.revealAfterSeconds + (row.revealAfterSeconds > 0 || row.role === "source" ? 0 : Math.min(row.segmentIndex*p.motion.lineDelaySeconds,.18));
}

/** Per reveal step `{start, needed, available}` as Film Type charges it. */
export function filmStepRequirements(moment: TimedMoment, p: { motion: Motion }): Array<{start:number;needed:number;available:number}> {
  const span=moment.endSeconds-moment.startSeconds;
  const starts=[...new Set(moment.segments.map(s=>s.revealAfterSeconds??0))].sort((a,b)=>a-b);
  return starts.map((start,i)=>{
    const group=moment.segments.map((s,index)=>({s,index})).filter(({s})=>(s.revealAfterSeconds??0)===start);
    const delay=Math.max(...group.map(({s,index})=>filmRowDelay({role:s.role,segmentIndex:index,revealAfterSeconds:start},p)-start));
    const enter=moment.presentation?.motion==="cut-in"?p.motion.cutInSeconds:p.motion.enterSeconds;
    const chars=group.reduce((sum,{s})=>sum+visibleLength(s.text)*(s.role==="source"?MOMENT_SOURCE_READ_WEIGHT:1),0);
    const blocks=group.filter(({s})=>s.role!=="source").length;
    const exit=i===starts.length-1?p.motion.exitSeconds:0;
    const needed=delay+Math.max(MOMENT_FIXATION_SECONDS,enter)+chars/MOMENT_READ_CPS+Math.max(0,blocks-1)*MOMENT_BLOCK_SECONDS+exit;
    const available=(starts[i+1]??span)-start;
    return {start,needed,available};
  });
}
