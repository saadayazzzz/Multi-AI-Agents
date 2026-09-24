import type { Metadata } from "next";
import { JetBrains_Mono, Michroma, Rajdhani } from "next/font/google";
import "./globals.css";

const display = Michroma({ weight: "400", subsets: ["latin"], variable: "--font-display" });
const sans = Rajdhani({ weight: ["400", "500", "600", "700"], subsets: ["latin"], variable: "--font-sans" });
// hinted for screens: stays sharp at the 9-11px sizes the panels use
const mono = JetBrains_Mono({ weight: ["400", "500"], subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "A.U.R.E.N.",
  description: "Autonomous UGC, Revenue & Engagement Nexus",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-void font-sans text-slate-200 antialiased">{children}</body>
    </html>
  );
}
