import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JARVIS Console",
  description: "Voice control plane for the autonomous content-marketing agent team",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-void font-sans text-slate-200 antialiased">
        {children}
      </body>
    </html>
  );
}
