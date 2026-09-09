/** Shared paint/planning contract: smooth truncated Gaussian, no flat plateau. */
export function diffuseAt(radius:number):number {
  const r=Math.max(0,radius);
  if(r>=1)return 0;
  // Gaussian multiplied by a smooth compact window: zero value/slope at rim.
  return Math.exp(-3*r*r)*Math.pow(1-r*r,2);
}
export function diffuseRadii(width:number,height:number,cfg:{radiusScale:number;minRadiusPx:number}) {
  return {rx:Math.max(cfg.minRadiusPx,width*cfg.radiusScale),ry:Math.max(cfg.minRadiusPx,height*cfg.radiusScale)};
}
export const diffuseStops=Array.from({length:97},(_,i)=>({offset:i/96,alpha:diffuseAt(i/96)}));
