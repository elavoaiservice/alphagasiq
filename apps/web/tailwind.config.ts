import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Re-skinned to the ElavoAI look (light, airy, sky-blue on navy). The
        // `terminal.*` token names are kept so the ~66 existing components pick
        // up the new palette without per-file edits; only the VALUES changed.
        terminal: {
          bg: "#f8fbff",      // page background (subtle blue tint)
          panel: "#ffffff",   // cards / panels
          border: "#dce7f5",  // pale blue-gray borders
          text: "#10233f",    // deep navy ink
          muted: "#5f708a",   // secondary text
          accent: "#29abe2",  // ElavoAI sky blue
          bull: "#16a34a",    // up / positive (readable on light)
          bear: "#dc2626",    // down / negative
          warn: "#d97706",    // caution amber
        },
        // ElavoAI brand blue.
        elavo: {
          blue: "#29abe2",
          blueLight: "#56ccf2",
          navy: "#10233f",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
