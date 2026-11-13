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
        bg: 'var(--bg)',
        surface: 'var(--surface)',
        raised: 'var(--raised)',
        sunken: 'var(--sunken)',
        line: 'var(--line)',
        'line-strong': 'var(--line-strong)',
        ink: 'var(--ink)',
        soft: 'var(--soft)',
        mute: 'var(--mute)',
        accent: 'var(--accent)',
        brand: {
          300: '#e49080',
          400: '#c0485a',
          500: '#8b2040',
          600: '#6b1830',
          700: '#43101e',
          800: '#2e1018',
          900: '#1c0a10',
        },
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        danger: 'var(--danger)',
        info: 'var(--info)',
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
