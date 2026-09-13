/** 2.4 only: bounded, deterministic full-dwell path search, never a timer.
 * Fades stay inside each safe interval. No movement across faces, no double brand.
 * Real shot/text/obstacle boundaries beat fallback grid points. Sites may recur.
 */
type Rect={x:number;y:number;w:number;h:number};
type Config={minDwellSeconds:number;maxRelocations:number;targetDwellSeconds?:number};
export function planMovingBrand(duration:number,shotTimes:number[],eventTimes:number[],order:string[],rects:Record<string,Rect>,clear:(r:Rect,a:number,b:number)=>boolean,cfg:Config,introDelay=0,diagnostics?:()=>string){
 const min=cfg.minDwellSeconds,target=cfg.targetDwellSeconds??12;
 const delay=Math.max(0,introDelay);
 if(delay>0&&delay>=duration)throw new Error("Film Type watermark intro delay covers the whole film; shorten it or author an empty watermark.");
 const visibleDuration=duration-delay;
 const minDwell=Math.min(min,visibleDuration);
 const shots=new Set([0,duration,...shotTimes]),events=new Set([...shots,...eventTimes]);
 if(delay>0)events.add(delay);
 for(let t=delay+min;t<duration;t+=min)events.add(t);
 const times=[...events].filter(t=>t>=0&&t<=duration).sort((a,b)=>a-b);
 if(times.length>512)throw new Error("Film Type moving-brand timeline exceeds 512 boundaries; split the review explicitly.");
 const maxCount=Math.max(1,Math.min(1+cfg.maxRelocations,Math.max(1,Math.floor(visibleDuration/min))));
 type State={cost:number;zone:string;mask:number;slots:{zone:string;start:number;end:number}[]};
 const seedIdx=delay>0?times.findIndex(t=>t>=delay-1e-9):0;
 if(delay>0&&seedIdx<1)throw new Error("Film Type watermark intro delay covers the whole film; shorten it or author an empty watermark.");
 let layer=new Map<string,State>([[`${seedIdx}:-1:0`,{cost:0,zone:"",mask:0,slots:[]}]]);
 const finals:State[]=[],valid=new Map<string,boolean>();
 for(let count=1;count<=maxCount;count++){
  const next=new Map<string,State>();
  for(const [key,state] of layer){const i=Number(key.split(":")[0]),start=times[i];
   for(let j=i+1;j<times.length;j++){
    const end=times[j],dwell=end-start,last=j===times.length-1;
    if(dwell+1e-8<minDwell||(!last&&duration-end<minDwell-1e-8))continue;
    for(const [z,zone] of order.entries()){
     if(zone===state.zone)continue;
     const ck=`${i}:${j}:${z}`;if(!valid.has(ck))valid.set(ck,clear(rects[zone],start,end));if(!valid.get(ck))continue;
     const mask=state.mask|(1<<z),cost=state.cost+Math.pow(dwell-target,2)*.1+z*.12+(last||shots.has(end)?0:1);
     const candidate={cost,zone,mask,slots:[...state.slots,{zone,start,end}]},nk=`${j}:${z}:${mask}`;
     if(!next.has(nk)||cost<next.get(nk)!.cost)next.set(nk,candidate);
    }
   }
  }
  for(const [key,state] of next)if(Number(key.split(":")[0])===times.length-1)finals.push(state);
  layer=next;
 }
 const eligible=finals.filter(s=>visibleDuration<2*min||s.slots.length>=2);
 const score=(s:State)=>s.cost-(s.slots.some(x=>x.zone.endsWith("left"))&&s.slots.some(x=>x.zone.endsWith("right"))?24:0);
 eligible.sort((a,b)=>score(a)-score(b));const best=eligible[0];
 if(!best)throw new Error("No safe moving watermark schedule: review text/subject regions; stationary or hidden fallback was not used. " + (diagnostics?.()??""));
 return best.slots.map((s,i)=>({zone:s.zone,startSeconds:s.start,endSeconds:s.end,rect:rects[s.zone],transition:i?"relocate-fade":"fade-in",reason:"Event-based full-dwell clearance; bounded relocation; side diversity preferred, not copy protection"}));
}


type CoverageConfig=Config&{
 minCoverageRatio?:number;targetCoverageRatio?:number;
 longFormThresholdSeconds?:number;minLongFormRelocations?:number;minLongFormVerticalBands?:number;verticalDiversityMinDwellSeconds?:number;
};
type CoverageSlot={zone:string;start:number;end:number};
type CoverageState={covered:number;cost:number;zone:string;mask:number;moves:number;slots:CoverageSlot[]};
const bitCount=(n:number)=>{let count=0;for(let v=n;v;v>>>=1)count+=v&1;return count;};
const verticalBandCount=(slots:CoverageSlot[])=>new Set(slots.map(slot=>slot.zone.split("-")[0])).size;
function betterCoverage(a:CoverageState,b:CoverageState|undefined,requiredMoves:number):boolean{
 if(!b)return true;
 if(Math.abs(a.covered-b.covered)>1e-8)return a.covered>b.covered;
 const am=Math.min(a.moves,requiredMoves),bm=Math.min(b.moves,requiredMoves);
 if(am!==bm)return am>bm;
 const az=bitCount(a.mask),bz=bitCount(b.mask);if(az!==bz)return az>bz;
 if(Math.abs(a.cost-b.cost)>1e-8)return a.cost<b.cost;
 return a.slots.length<b.slots.length;
}

/** 2.13 only: optimize safe visible coverage over timeline intervals and zones.
 * Gaps are legal; unsafe intervals are never repaired by trimming one chosen path.
 */
export function planCoverageAwareBrand(duration:number,boundaries:number[],order:string[],
 rects:Record<string,Rect>,clear:(r:Rect,a:number,b:number)=>boolean,cfg:CoverageConfig,
 introDelay=0,diagnostics?:()=>string){
 const min=cfg.minDwellSeconds,target=cfg.targetDwellSeconds??12,delay=Math.max(0,introDelay);
 if(delay>0&&delay>=duration)throw new Error("Film Type watermark intro delay covers the whole film; shorten it or author an empty watermark.");
 const visibleDuration=duration-delay;
 const minDwell=duration<20?Math.min(min,visibleDuration):min;
 const events=new Set<number>([delay,duration,...boundaries.filter(t=>Number.isFinite(t)&&t>=delay&&t<=duration)]);
 for(let t=delay+minDwell;t<duration;t+=minDwell)events.add(t);
 const times=[...events].sort((a,b)=>a-b);if(times.length>512)throw new Error("Film Type coverage-aware watermark timeline exceeds 512 boundaries; split the review explicitly.");
 const maxRelocations=Math.max(0,cfg.maxRelocations),maxSlots=1+maxRelocations;
 const longForm=duration>=(cfg.longFormThresholdSeconds??Infinity);
 const requiredMoves=longForm?Math.max(0,cfg.minLongFormRelocations??0):0;
 const requiredBands=longForm?Math.max(0,cfg.minLongFormVerticalBands??0):0;
 const diversityMinDwell=longForm?Math.min(min,Math.max(0,cfg.verticalDiversityMinDwellSeconds??min)):min;
 const layers=Array.from({length:times.length},()=>new Map<string,CoverageState>());
 layers[0].set("0::0:0",{covered:0,cost:0,zone:"",mask:0,moves:0,slots:[]});
 const push=(at:number,state:CoverageState)=>{
  const key=`${state.slots.length}:${state.zone}:${state.mask}:${state.moves}`;
  if(betterCoverage(state,layers[at].get(key),requiredMoves))layers[at].set(key,state);
 };
 const valid=new Map<string,boolean>();
 for(let i=0;i<times.length-1;i++){
  for(const state of layers[i].values()){
   push(i+1,state);
   if(state.slots.length>=maxSlots)continue;
   for(let j=i+1;j<times.length;j++){
    const start=times[i],end=times[j],dwell=end-start;
    for(const [z,zone] of order.entries()){
     const band=zone.split("-")[0];
     const existingBands=new Set(state.slots.map(slot=>slot.zone.split("-")[0]));
     const diversityException=dwell+1e-8<minDwell && longForm && requiredBands>0
      && state.slots.length>0 && !existingBands.has(band) && dwell+1e-8>=diversityMinDwell;
     if(dwell+1e-8<minDwell&&!diversityException)continue;
     const ck=`${i}:${j}:${z}`;
     if(!valid.has(ck))valid.set(ck,clear(rects[zone],start,end));
     if(!valid.get(ck))continue;
     const moves=state.zone&&state.zone!==zone?state.moves+1:state.moves;
     if(moves>maxRelocations)continue;
     const mask=state.mask|(1<<z);
     const topPenalty=zone.startsWith("upper")?0.18:0;
     const diversityPenalty=diversityException?0.75:0;
     const cost=state.cost+Math.pow(dwell-target,2)*.1+z*.12+topPenalty+diversityPenalty;
     push(j,{covered:state.covered+dwell,cost,zone,mask,moves,
      slots:[...state.slots,{zone,start,end}]});
    }
   }
  }
 }
 const finals=[...layers[times.length-1].values()].filter(state=>state.slots.length>0);
 const floorSeconds=duration*(cfg.minCoverageRatio??0);
 const protectedPool=finals.filter(state=>state.covered+1e-8>=floorSeconds
  && state.moves>=requiredMoves && verticalBandCount(state.slots)>=requiredBands);
 const pool=protectedPool.length?protectedPool:finals;
 pool.sort((a,b)=>betterCoverage(a,b,requiredMoves)?-1:betterCoverage(b,a,requiredMoves)?1:0);
 const best=pool[0];
 if(!best)throw new Error("No safe coverage-aware watermark schedule: review text/subject regions or explicitly author an empty watermark. "+(diagnostics?.()??""));
 return best.slots.map((slot,index)=>({zone:slot.zone,startSeconds:slot.start,endSeconds:slot.end,
  rect:rects[slot.zone],transition:index?"relocate-fade":"fade-in",
  reason:"Coverage-aware full-dwell clearance; unsafe intervals replanned across alternate zones"}));
}
