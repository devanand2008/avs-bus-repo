import type { Metadata,Viewport } from 'next';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import './globals.css';
import './telemetry.css';
import './blueprint.css';
import 'maplibre-gl/dist/maplibre-gl.css';
export const metadata:Metadata={title:`${process.env.COLLEGE_NAME||'AVS Engineering College'} | College Fleet Command`,description:`Fleet operations, accountable fuel governance and GPS intelligence for ${process.env.COLLEGE_NAME||'AVS Engineering College'}.`,manifest:'/manifest.webmanifest',appleWebApp:{capable:true,title:'AVS Fleet',statusBarStyle:'default'},icons:{icon:[{url:'/brand/favicon-32.png',sizes:'32x32',type:'image/png'}],apple:'/brand/apple-touch-icon.png',shortcut:'/favicon.ico'}};
export const viewport:Viewport={width:'device-width',initialScale:1,themeColor:'#122b3b'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>;}
