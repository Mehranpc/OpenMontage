/** Shared paint/planning contract: smooth truncated Gaussian, no flat plateau. */
export function diffuseAt(radius:number):number {
  const r=Math.max(0,radius);
  if(r>=1)return 0;
  // Gaussian multiplied by a smooth compact window: zero value/slope at rim.
  return Math.exp(-3*r*r)*Math.pow(1-r*r,2);
}
/** When a frame is supplied (2.9.0), the field is bounded by the video itself:
 * its full width/height can never exceed the frame, so the shadow cannot grow
 * past the edges and read as a large pale wash. The falloff curve is unchanged,
 * so a smaller field simply fades to nothing sooner and more naturally.
 * Older pinned profiles pass no frame and keep their original radii exactly. */
export function diffuseRadii(width:number,height:number,cfg:{radiusScale:number;minRadiusPx:number},frame?:{width:number;height:number}) {
  let rx=Math.max(cfg.minRadiusPx,width*cfg.radiusScale),ry=Math.max(cfg.minRadiusPx,height*cfg.radiusScale);
  if(frame){
    if(!(Number.isFinite(frame.width)&&Number.isFinite(frame.height)&&frame.width>0&&frame.height>0)) throw new Error("Film Type diffuse field requires real frame dimensions; estimated bounds are not accepted.");
    rx=Math.min(rx,frame.width/2);
    ry=Math.min(ry,frame.height/2);
  }
  return {rx,ry};
}
export const diffuseStops=Array.from({length:97},(_,i)=>({offset:i/96,alpha:diffuseAt(i/96)}));
