import * as SecureStore from 'expo-secure-store';
import {Platform} from 'react-native';
export type Row=Record<string,any>;
export const API=(process.env.EXPO_PUBLIC_API_URL||'http://localhost:8000').replace(/\/$/,'')+'/api/v2';
let token:string|null=null;
export const getToken=()=>token;
export async function restoreSession(){if(Platform.OS!=='web')token=await SecureStore.getItemAsync('cfc-session');}
export async function saveToken(value:string|null){token=value;if(Platform.OS!=='web'){if(value)await SecureStore.setItemAsync('cfc-session',value);else await SecureStore.deleteItemAsync('cfc-session');}}
export async function request<T=Row>(path:string,method='GET',body?:any):Promise<T>{const headers:Record<string,string>={'X-Client':'native'};if(token)headers.Authorization='Bearer '+token;if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';const r=await fetch(API+path,{method,headers,credentials:'include',body:body instanceof FormData?body:body?JSON.stringify(body):undefined});if(!r.ok){let message;try{message=(await r.json()).detail;}catch{message='API is unavailable';}throw new Error(typeof message==='string'?message:JSON.stringify(message));}return r.json();}
export function fmt(v:any,places=1){return v===null||v===undefined?'Unknown':Number(v).toLocaleString('en-IN',{maximumFractionDigits:Number(v)!==0&&Math.abs(Number(v))<1?Math.max(places,3):places});}
export const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export function addDate(d:string,n:number){const v=new Date(d+'T12:00:00Z');v.setUTCDate(v.getUTCDate()+n);return v.toISOString().slice(0,10);}
