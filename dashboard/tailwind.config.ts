import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#05070d",
        panel: "#0b1020",
        edge: "#1c2740",
        jarvis: {
          DEFAULT: "#38e0d0",
          dim: "#1c6f6a",
          amber: "#ffb454",
          red: "#ff5c72",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 0 40px -8px rgba(56,224,208,0.45)",
      },
    },
  },
  plugins: [],
};

export default config;
