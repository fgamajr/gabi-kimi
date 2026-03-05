import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Backgrounds em escala mais clean
        canvas: "#0A0A0F",
        base: "#12121A",
        raised: "#1A1A25",
        overlay: "#22222E",
        sunken: "#2A2A38",
        
        // Brand Nubank
        brand: {
          DEFAULT: "#820AD1",
          light: "#9B2DFF",
          dark: "#6A08AA",
          glow: "rgba(130, 10, 209, 0.15)",
        },
        
        // Accent (teal/ciano mais suave)
        accent: {
          DEFAULT: "#00D9C0",
          light: "#4DFFE5",
          glow: "rgba(0, 217, 192, 0.12)",
        },
        
        // Seções DOU (mais suaves)
        secao: {
          1: "#5BA3FF",
          2: "#FFB347",
          3: "#C77DFF",
          e: "#FF6B7A",
        },
        
        // Texto (mais contraste)
        primary: "#FFFFFF",
        secondary: "#B8B8C8",
        muted: "#6E6E80",
        disabled: "#4A4A5C",
        
        // Feedback (mais suaves)
        success: "#00C896",
        warning: "#FFB800",
        error: "#FF5470",
        info: "#5BA3FF",
        
        // Bordas
        border: "rgba(255,255,255,0.06)",
        "border-strong": "rgba(255,255,255,0.12)",
        "border-focus": "rgba(130, 10, 209, 0.5)",
      },
      fontFamily: {
        display: ["var(--font-syne)", "system-ui", "sans-serif"],
        body: ["var(--font-crimson)", "Georgia", "serif"],
        mono: ["var(--font-jetbrains)", "monospace"],
      },
      fontSize: {
        "2xs": ["11px", { lineHeight: "1.4" }],
        xs: ["12px", { lineHeight: "1.5" }],
        sm: ["14px", { lineHeight: "1.5" }],
        base: ["16px", { lineHeight: "1.6" }],
        md: ["18px", { lineHeight: "1.6" }],
        lg: ["20px", { lineHeight: "1.5" }],
        xl: ["24px", { lineHeight: "1.3" }],
        "2xl": ["28px", { lineHeight: "1.2" }],
        "3xl": ["36px", { lineHeight: "1.1" }],
      },
      spacing: {
        "18": "4.5rem",
        "22": "5.5rem",
      },
      borderRadius: {
        "2xl": "1rem",
        "3xl": "1.5rem",
      },
      boxShadow: {
        'elevated': '0 1px 2px rgba(0,0,0,0.1), 0 4px 12px rgba(0,0,0,0.1)',
        'card': '0 4px 20px rgba(0,0,0,0.15)',
        'brand': '0 2px 8px rgba(130, 10, 209, 0.15)',
        'brand-lg': '0 4px 16px rgba(130, 10, 209, 0.2)',
      },
      transitionTimingFunction: {
        "out-custom": "cubic-bezier(0.0, 0.0, 0.2, 1.0)",
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1.0)",
      },
      animation: {
        "shimmer": "shimmer 2s infinite",
        "fade-in": "fadeIn 0.2s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
      },
      keyframes: {
        shimmer: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
      },
    },
  },
  plugins: [
    function({ addUtilities }: { addUtilities: Function }) {
      addUtilities({
        '.touch-manipulation': {
          'touch-action': 'manipulation',
        },
        '.safe-area-inset-bottom': {
          'padding-bottom': 'env(safe-area-inset-bottom)',
        },
        '.scrollbar-hide': {
          '-ms-overflow-style': 'none',
          'scrollbar-width': 'none',
          '&::-webkit-scrollbar': {
            display: 'none',
          },
        },
        '.text-balance': {
          'text-wrap': 'balance',
        },
      });
    },
  ],
};

export default config;
