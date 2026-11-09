import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

// 숫자·타임코드·키 이름용 고정폭. 본문은 Pretendard(아래 <link>, 한글 가변 폰트 동적 서브셋)
const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  weight: ["400", "500", "600"],
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ShortForge Studio",
  description: "잘 된 숏폼의 구조를, 내 이야기로 — 7단계 숏폼 제작 스튜디오",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme은 아래 스크립트가 그리기 전에 바꾼다 (서버 렌더 값과 달라도 경고하지 않게)
    <html lang="ko" className={jetbrains.variable} data-theme="dark" suppressHydrationWarning>
      <head>
        <script
          // 저장된 화면 밝기를 첫 그림 전에 넣는다 (밝은 테마에서 어두운 화면이 번쩍이지 않게)
          dangerouslySetInnerHTML={{
            __html:
              "try{var t=localStorage.getItem('sf-theme');if(t==='light'||t==='system')document.documentElement.dataset.theme=t}catch(e){}",
          }}
        />
        {/* Pretendard는 Google Fonts에 없어 CDN 스타일시트(한글 가변 폰트 동적 서브셋)로 받는다 */}
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
        />
      </head>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
