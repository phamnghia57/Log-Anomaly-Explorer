import type { VercelConfig } from '@vercel/config/v1';

const target = process.env.API_PROXY_TARGET;
if (!target || new URL(target).protocol !== 'https:' || new URL(target).username || new URL(target).password
    || new URL(target).pathname !== '/' || new URL(target).search || new URL(target).hash) {
  throw new Error('API_PROXY_TARGET must be an HTTPS backend origin without credentials or path');
}
export const config: VercelConfig = {
  rewrites: [
    { source: '/api/:path*', destination: `${target.replace(/\/$/, '')}/:path*` },
    { source: '/(.*)', destination: '/index.html' },
  ],
  headers: [{ source: '/api/:path*', headers: [{ key: 'Cache-Control', value: 'no-store' }] }],
};
