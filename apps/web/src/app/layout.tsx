import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  // `default` is the tab title for pages that set none (the root redirect, the
  // auth pages); `template` wraps a page's own title, so /runs reads
  // "Agent runs · ASEP" instead of every tab showing the same name.
  title: {
    default: "ASEP — AI Software Engineering Platform",
    template: "%s · ASEP",
  },
  description:
    "An AI-native platform that plans, implements, reviews, tests, and documents software with you.",
};

// The app is dark-only; tell the browser so form controls, scrollbars, and the
// mobile address bar match instead of flashing a light chrome.
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#09090b", // zinc-950 — the body background
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans">{children}</body>
    </html>
  );
}
