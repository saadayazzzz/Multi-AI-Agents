import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#05070d",
        panel: "#0b1120",
        edge: "#1e2a44",
        jarvis: {
          DEFAULT: "#38e0d0",
          soft: "#7cf5ea",
          dim: "#1c6f6a",
          amber: "#ffb454",
          red: "#ff5c72",
          ok: "#43d9a3",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 32px -8px rgba(56,224,208,0.5)",
        panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 40px -24px rgba(0,0,0,0.9)",
      },
    },
  },
  plugins: [],
};

export default config;
