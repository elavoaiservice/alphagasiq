import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Re-skinned to the EXACT ElavoAI Business Center (dashboard) palette:
        // Tailwind gray scale for surfaces/ink + the #29ABE2 brand blues. The
        // `terminal.*` token names are kept so all ~52 existing components pick
        // up the palette without per-file edits; only the VALUES changed.
        terminal: {
          bg: "#f9fafb",      // page background — gray-50
          panel: "#ffffff",   // cards / panels — white
          border: "#e5e7eb",  // card borders — gray-200
          text: "#111827",    // headings — gray-900
          muted: "#6b7280",   // secondary text — gray-500
          accent: "#29abe2",  // ElavoAI brand blue
          bull: "#16a34a",    // up / positive — green-600
          bear: "#dc2626",    // down / negative — red-600
          warn: "#f59e0b",    // caution — amber-500
        },
        // ElavoAI brand blues + light-blue tints (exact dashboard values).
        elavo: {
          blue: "#29abe2",      // primary brand blue
          blueDark: "#1f96c8",  // hover / links
          blueDeep: "#1882ae",  // deep accent (avatar ink)
          blueLight: "#56ccf2", // light accent (used on the dark landing page)
          navy: "#10233f",      // marketing / login navy
          skyTint: "#f0f9ff",   // pale hover background
          skyBg: "#e0f4fc",     // pale badge background
          skyRing: "#c8e6f7",   // pale ring / divider
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
