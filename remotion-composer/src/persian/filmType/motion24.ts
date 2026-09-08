/** 2.4/2.5: pure frame-driven math shared by paint and tests. */
const clamp=(x:number)=>Math.max(0,Math.min(1,x));
export const smooth=(x:number)=>{const t=clamp(x);return t*t*(3-2*t);};
/** Concave shadow rolloff: brightness falls slowly at the core edge and
 * lingers toward the rim, so the field dissolves like a soft shadow instead
 * of reading as a flat dark plate with a hard rim. Curve 1 is the old ramp. */
export const featherCurve=(x:number,curve:number)=>{const t=clamp(x);return Math.pow(t,curve);};
export function gentleLife(seconds:number,span:number,delay:number,enter:number,exit:number){
 const available=Math.max(.001,span-delay),arrive=smooth((seconds-delay)/Math.min(enter,available/2)),leave=smooth((span-seconds)/Math.min(exit,available/2));
 return {arrive,leave,opacity:arrive*leave};
}
/** Nested alpha composition: exact full-strength core, finite smooth feather. */
export function featherLayers(feather:number,steps:number,curve=1){
 if(!Number.isFinite(feather)||feather<=0||!Number.isInteger(steps)||steps<8||steps>128)throw new Error("Invalid compact field feather");
 if(!Number.isFinite(curve)||curve<1||curve>3)throw new Error("Invalid compact field feather curve");
 let previous=0;
 return Array.from({length:steps+1},(_,i)=>{const value=smooth(featherCurve(i/steps,curve)),alpha=previous===1?0:(value-previous)/(1-previous);previous=value;return {expand:feather*(1-i/steps),alpha};});
}
/** A convex superellipse cloud, not a rectangular badge. The padded text box
 * is inscribed in the core. Exponent 3 needs 2^(1/3), not the old ellipse sqrt(2).
 */
export function compactPath(width:number,height:number,padding:number,expand:number,exponent:number){
 if(![width,height,padding,expand,exponent].every(Number.isFinite)||width<=0||height<=0||padding<0||expand<0||exponent<2||exponent>4)throw new Error("Invalid compact field geometry");
 const corner=Math.pow(2,1/exponent),a=(width/2+padding)*corner+expand,b=(height/2+padding)*corner+expand,power=2/exponent;
 return Array.from({length:96},(_,i)=>{const angle=i*Math.PI*2/96,c=Math.cos(angle),s=Math.sin(angle);return `${i?'L':'M'}${(a*Math.sign(c)*Math.pow(Math.abs(c),power)).toFixed(3)} ${(b*Math.sign(s)*Math.pow(Math.abs(s),power)).toFixed(3)}`;}).join(' ')+' Z';
}
