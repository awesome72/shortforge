import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans_KR, Space_Grotesk } from "next/font/google";
import "./globals.css";

const plexKr = IBM_Plex_Sans_KR({
  variable: "--font-plex-kr",
  weight: ["400", "500", "600"],
  subsets: ["latin"],
  preload: false, // 한글 글리프는 용량이 커서 미리 받지 않는다
});
const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  weight: ["400", "500"],
  subsets: ["latin"],
});
const grotesk = Space_Grotesk({
  variable: "--font-grotesk",
  weight: ["500", "700"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ShortForge",
  description: "잘 된 숏폼의 구조를, 내 이야기로 — 7단계 숏폼 제작 워크스페이스",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${plexKr.variable} ${plexMono.variable} ${grotesk.variable}`}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
