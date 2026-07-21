import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export", // static bundle served by the FastAPI bridge (ADR-015)
  images: { unoptimized: true },
};

export default nextConfig;
