/** @type {import('tailwindcss').Config} */
// Tokens of the "midnight and iris" theme. The values live in src/index.css; the brand scale is here.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      colors: {
        // Channel variables (see index.css) so opacity modifiers such as bg-ok/10 work.
        bg: 'rgb(var(--bg-rgb) / <alpha-value>)',
        surface: 'rgb(var(--surface-rgb) / <alpha-value>)',
        raised: 'rgb(var(--raised-rgb) / <alpha-value>)',
        sunken: 'rgb(var(--sunken-rgb) / <alpha-value>)',
        line: 'var(--line)',
        'line-strong': 'var(--line-strong)',
        ink: 'rgb(var(--ink-rgb) / <alpha-value>)',
        soft: 'rgb(var(--soft-rgb) / <alpha-value>)',
        mute: 'rgb(var(--mute-rgb) / <alpha-value>)',
        accent: 'rgb(var(--accent-rgb) / <alpha-value>)',
        brand: {
          300: '#c7cdff',
          400: '#8e99f5',
          500: '#4f5bd5',
          600: '#4450c4',
          700: '#353e96',
          800: '#232a66',
          900: '#151a40',
        },
        ok: 'rgb(var(--ok-rgb) / <alpha-value>)',
        warn: 'rgb(var(--warn-rgb) / <alpha-value>)',
        danger: 'rgb(var(--danger-rgb) / <alpha-value>)',
        info: 'rgb(var(--info-rgb) / <alpha-value>)',
      },
      borderRadius: {
        card: '16px',
        btn: '10px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(2,4,10,0.45), 0 8px 24px rgba(2,4,10,0.28)',
        pop: '0 12px 32px rgba(2,4,10,0.6), 0 2px 6px rgba(2,4,10,0.4)',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.25, 1, 0.5, 1)',
      },
    },
  },
  plugins: [],
};
