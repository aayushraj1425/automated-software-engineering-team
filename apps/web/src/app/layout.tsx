import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ASEP — AI Software Engineering Platform",
  description:
    "An AI-native platform that plans, implements, reviews, tests, and documents software with you.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">{children}</body>
    </html>
  );
}
