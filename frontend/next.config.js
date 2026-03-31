/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Enable Tauri compatibility — output as static export for desktop wrapping
  output: process.env.TAURI_BUILD === 'true' ? 'export' : undefined,
  allowedDevOrigins: ['127.0.0.1'],
};

module.exports = nextConfig;
