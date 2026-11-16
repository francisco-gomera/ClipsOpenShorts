/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Cyan Dark token system — values mirror tokens.css
        // Using CSS var() with <alpha-value> fallback for Tailwind opacity modifiers
        background:       "#101820",
        surface:          "#19252D",
        "surface-elevated": "#22323B",
        border:           "#30434C",
        primary:          "#35C9D0",
        "primary-hover":  "#53DDE1",
        "primary-soft":   "#173B40",
        "text-primary":   "#F2F7F8",
        "text-secondary": "#A5B6BC",
        success:          "#55D6A5",
        warning:          "#F4BD68",
        error:            "#FF777F",
      },
      fontFamily: {
        brand: "var(--font-brand)",
        ui:    "var(--font-ui)",
        sans:  "var(--font-ui)",
        mono:  "var(--font-mono)",
      },
      borderColor: {
        DEFAULT: "#30434C",
        border:  "#30434C",
      },
      borderRadius: {
        card:  "var(--radius-card)",
        btn:   "var(--radius-btn)",
        input: "var(--radius-input)",
        pill:  "var(--radius-pill)",
        sm:    "var(--radius-sm)",
      },
      fontSize: {
        micro: ["10.5px", { letterSpacing: "0.10em" }],
      },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade': 'fadeIn 0.4s var(--ease-out)',
        // mobile shell: the nav drawer flies in from the edge, sheets rise
        'slide-in-left': 'slideInLeft 0.24s var(--ease-out)',
        'sheet-up': 'sheetUp 0.26s var(--ease-out)',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        slideInLeft: {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        sheetUp: {
          from: { transform: 'translateY(12px)', opacity: '0' },
          to: { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
