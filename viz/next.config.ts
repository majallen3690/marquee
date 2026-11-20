import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export", // static bundle served by the FastAPI bridge (ADR-015)
  images: { unoptimized: true },
  // The GitHub Pages build (NEXT_PUBLIC_MARQUEE_STATIC=1) lives under /<repo>/.
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
};

export default nextConfig;
