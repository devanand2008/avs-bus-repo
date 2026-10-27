export type Row = Record<string, any>;
export type User = {id:string;name:string;email:string;role:string;mfa_enabled:boolean;driver_id:string|null};
export const API = '/api/v2';
export async function api<T=Row>(path:string, init:RequestInit={}):Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type','application/json');
  const response=await fetch(API+path,{...init,headers,credentials:'include',cache:'no-store'});
  if (!response.ok) {
    let detail:any;
    try { detail=(await response.json()).detail; } catch { detail=`Request failed (${response.status})`; }
    const message=typeof detail==='string'?detail:JSON.stringify(detail);
    throw new Error(message||`Request failed (${response.status})`);
  }
  return response.json();
}
export const post=<T=Row>(path:string,body:any={})=>api<T>(path,{method:'POST',body:JSON.stringify(body)});
export async function download(path:string,filename:string) {
  const r=await fetch(API+path,{credentials:'include'});
  if(!r.ok) { const data=await r.json();throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)); }
  const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
}
export function number(value:any,places=1):string {return value===null||value===undefined?'—':Number(value).toLocaleString('en-IN',{maximumFractionDigits:Number(value)!==0&&Math.abs(Number(value))<1?Math.max(places,3):places});}
export const istToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export function addDay(day:string,n:number){const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}
export function presetDates(key:string,weekStart=0):[string,string] {
  const t=istToday();const d=new Date(t+'T12:00:00Z');
  if(key==='yesterday')return [addDay(t,-1),t];
  if(key==='this_week'||key==='last_week'){const offset=((d.getUTCDay()+6)%7-weekStart+7)%7;const a=addDay(t,-offset-(key==='last_week'?7:0));return [a,addDay(a,7)];}
  if(key==='this_month'||key==='last_month'){const a=t.slice(0,8)+'01';if(key==='last_month')return [addDay(a,-1).slice(0,8)+'01',a];const n=new Date(a+'T12:00:00Z');n.setUTCMonth(n.getUTCMonth()+1);return [a,n.toISOString().slice(0,10)];}
  return [t,addDay(t,1)];
}
