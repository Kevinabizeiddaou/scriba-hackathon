// Transferred unchanged from Scriba: Gmail/frontend/tailwind.config.js @ 3ae3a2aa.
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', '"Segoe UI"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px', letterSpacing: '0.01em' }],
        'xs':  ['11px', { lineHeight: '16px' }],
        'sm':  ['12.5px', { lineHeight: '18px' }],
        'base':['14px',  { lineHeight: '22px' }],
        'md':  ['15px',  { lineHeight: '22px' }],
        'lg':  ['16px',  { lineHeight: '24px' }],
        'xl':  ['18px',  { lineHeight: '26px' }],
        '2xl': ['21px',  { lineHeight: '30px' }],
        '3xl': ['24px',  { lineHeight: '32px' }],
        '4xl': ['30px',  { lineHeight: '38px' }],
        '5xl': ['36px',  { lineHeight: '44px' }],
      },
      colors: {
        brand: {
          50:  '#fdf6f2',
          100: '#faeae3',
          200: '#f2c8b6',
          300: '#e49080',
          400: '#c0485a',
          500: '#8b2040',
          600: '#6b1830',
          700: '#43101e',
          800: '#2e1018',
          900: '#1c0a10',
        },
      },
      borderRadius: {
        card: '18px',
        btn:  '10px',
        sm:   '7px',
        xs:   '5px',
      },
      boxShadow: {
        'xs':    '0 1px 2px rgba(74,25,40,0.05)',
        'card':  '0 1px 3px rgba(74,25,40,0.06), 0 4px 12px rgba(74,25,40,0.05)',
        'hover': '0 8px 28px rgba(74,25,40,0.12), 0 2px 6px rgba(74,25,40,0.06)',
        'md':    '0 4px 16px rgba(74,25,40,0.09), 0 1px 4px rgba(74,25,40,0.05)',
        'xl':    '0 20px 56px rgba(74,25,40,0.15), 0 4px 12px rgba(74,25,40,0.07)',
        'ring':  '0 0 0 3px rgba(107,24,48,0.13)',
      },
      transitionTimingFunction: {
        'out':    'cubic-bezier(0.25, 1, 0.5, 1)',
        'in':     'cubic-bezier(0.5, 0, 0.75, 0)',
        'inout':  'cubic-bezier(0.76, 0, 0.24, 1)',
        'spring': 'cubic-bezier(0.34, 1.36, 0.64, 1)',
      },
      transitionDuration: {
        '120': '120ms',
        '160': '160ms',
        '220': '220ms',
        '260': '260ms',
      },
      spacing: {
        '13': '52px',
        '15': '60px',
        '18': '72px',
      },
    },
  },
  plugins: [],
}
