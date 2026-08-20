import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Iceberg Research",
  description: "自主多 Agent 学术研究系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh" className="h-full">
      <body className="h-full overflow-hidden flex flex-col">{children}</body>
    </html>
  );
}
