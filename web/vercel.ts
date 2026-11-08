import { routes, type VercelConfig } from '@vercel/config/v1';

const target = process.env.API_PROXY_TARGET;
if (!target || new URL(target).protocol !== 'https:' || new URL(target).username || new URL(target).password
    || new URL(target).pathname !== '/' || new URL(target).search || new URL(target).hash) {
  throw new Error('API_PROXY_TARGET must be an HTTPS backend origin without credentials or path');
}
// Export the evaluated config, rather than a named object that the deployment
// preflight can extract statically without evaluating its dynamic destination.
const config: VercelConfig = {
  rewrites: [
    routes.rewrite('/api/:path*', `${target.replace(/\/$/, '')}/:path*`),
    routes.rewrite('/(.*)', '/index.html'),
  ],
  headers: [{ source: '/api/:path*', headers: [{ key: 'Cache-Control', value: 'no-store' }] }],
};

export default config;
