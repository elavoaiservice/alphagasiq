/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next 16's `next dev` auto-generates AGENTS.md/CLAUDE.md scaffolding files by
  // default; this repo maintains its own docs/ and doesn't want generated meta-files
  // appearing at apps/web's root.
  agentRules: false,
};

export default nextConfig;
