import type { Config } from "tailwindcss";

// Palette sampled from the FUTUREWORK mockup (deep navy surfaces, blue/cyan/violet accents)
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#050A17", sidebar: "#070D1C", panel: "#0A1326", panel2: "#0E1A33", line: "#16233F",
        brand: "#3B82F6", cyan: "#22D3EE", violet: "#8B5CF6", ok: "#22C55E", warn: "#F59E0B", bad: "#EF4444",
        muted: "#8A97B2",
      },
    },
  },
  plugins: [],
} satisfies Config;
