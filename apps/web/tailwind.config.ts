import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0a0e14",
          panel: "#11161f",
          border: "#1f2733",
          text: "#d5dae3",
          muted: "#7c8798",
          accent: "#3fb6a8",
          bull: "#3ecf8e",
          bear: "#e5534b",
          warn: "#e0a941",
        },
        // Elavo-brand electric blue — used on the public marketing site
        // (landing/login/contact) to distinguish it from the platform's teal accent.
        elavo: {
          blue: "#2f6fed",
          blueLight: "#6b9bff",
          navy: "#060a12",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
