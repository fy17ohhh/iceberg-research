import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Iceberg Research",
  description: "A multi-agent deep research system.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full overflow-hidden flex flex-col">{children}</body>
    </html>
  );
}
