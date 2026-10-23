import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // start.bat(프로덕션 .next)을 띄운 채로 개발 서버를 따로 돌릴 때 NEXT_DIST_DIR=.next-dev처럼 폴더를 나눈다
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
