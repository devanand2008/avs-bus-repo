import Image from 'next/image';

/** The college-supplied application artwork, shared by all web brand surfaces. */
export default function BrandLogo({size=52,className=''}:{size?:number;className?:string}){
 return <Image src="/brand/logo.png" alt="College Fleet Fuel & GPS Monitor logo" width={size} height={size} className={`brand-logo ${className}`} unoptimized/>;
}
