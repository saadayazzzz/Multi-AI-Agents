import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#02050a",
        panel: "#06101c",
        edge: "#123049",
        jarvis: {
          DEFAULT: "#5ad8ff",
          soft: "#c4f4ff",
          dim: "#1b5a7a",
          amber: "#ffab40",
          red: "#ff4d5e",
          ok: "#4dffa6",
        },
      },
      fontFamily: {
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 32px -8px rgba(90,216,255,0.55)",
        panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 40px -24px rgba(0,0,0,0.9)",
      },
    },
  },
  plugins: [],
};

export default config;
