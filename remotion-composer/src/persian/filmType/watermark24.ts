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
