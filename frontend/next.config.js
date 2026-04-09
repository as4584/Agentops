/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Enable Tauri compatibility — output as static export for desktop wrapping
  // Docker builds set DOCKER_BUILD=true → standalone mode for minimal container
  output: process.env.TAURI_BUILD === 'true'
    ? 'export'
    : process.env.DOCKER_BUILD === 'true'
      ? 'standalone'
      : undefined,
  allowedDevOrigins: ['127.0.0.1'],
  async rewrites() {
    return [
      {
        source: '/preview/:path*',
        destination: 'http://127.0.0.1:8000/preview/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
