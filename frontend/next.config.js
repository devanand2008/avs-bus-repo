const nextConfig = {
  turbopack: { root: require('path').resolve(__dirname, '..') },
  distDir: process.env.CFC_DIST_DIR || (process.env.VERCEL ? '.next' : '.cfc-next'),
  reactStrictMode: true,
  async rewrites() { return process.env.VERCEL ? [] : [{ source:'/api/:path*', destination:(process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000')+'/api/:path*' }]; },
  async headers() { return [{ source:'/:path*', headers:[{key:'X-Content-Type-Options',value:'nosniff'},{key:'Referrer-Policy',value:'same-origin'},{key:'X-Frame-Options',value:'DENY'}] }]; }
};
module.exports = nextConfig;
