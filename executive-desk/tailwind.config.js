/** @type {import('tailwindcss').Config} */
// Tokens follow Scriba's dark burgundy theme (values re-declared here; nothing is imported from Scriba).
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
          300: '#e49080',
          400: '#c0485a',
          500: '#8b2040',
          600: '#6b1830',
          700: '#43101e',
          800: '#2e1018',
          900: '#1c0a10',
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
        card: '0 1px 3px rgba(0,0,0,0.40), 0 4px 12px rgba(0,0,0,0.30)',
        pop: '0 8px 28px rgba(0,0,0,0.55), 0 2px 6px rgba(0,0,0,0.40)',
      },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.25, 1, 0.5, 1)',
      },
    },
  },
  plugins: [],
};
