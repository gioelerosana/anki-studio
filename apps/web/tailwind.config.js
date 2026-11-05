// I colori puntano alle variabili di packages/ui-kit/src/theme.css (design
// system T3 Code). `withAlpha` fa funzionare i modificatori di opacità
// (`bg-primary/10`) anche su variabili oklch/rgba tramite color-mix.
const withAlpha = (name) => `color-mix(in oklab, var(--${name}) calc(<alpha-value> * 100%), transparent)`;

const tokens = [
  'background',
  'foreground',
  'card',
  'card-foreground',
  'popover',
  'popover-foreground',
  'primary',
  'primary-foreground',
  'secondary',
  'secondary-foreground',
  'muted',
  'muted-foreground',
  'accent',
  'accent-foreground',
  'border',
  'input',
  'ring',
  'error',
  'error-foreground',
  'info',
  'info-foreground',
  'success',
  'success-foreground',
  'warning',
  'warning-foreground',
  'sidebar',
  'sidebar-control-surface',
  'sidebar-row-active',
];

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
    '../../packages/ui-kit/src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(tokens.map((t) => [t, withAlpha(t)])),
        destructive: withAlpha('error'),
      },
      fontFamily: {
        sans: 'var(--font-sans)',
        mono: 'var(--font-mono)',
      },
      fontSize: {
        '2xs': ['11px', '16px'],
        '3xs': ['10px', '14px'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        control: 'var(--control-radius)',
        DEFAULT: 'var(--radius)',
        lg: 'var(--radius)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
      },
      boxShadow: {
        control: 'var(--shadow-control)',
        composer: 'var(--shadow-composer)',
        dialog: 'var(--shadow-dialog)',
        'control-highlight': 'var(--inset-shadow-control-highlight)',
        'control-pressed': 'var(--inset-shadow-control-pressed)',
      },
      // 8/16/24/32: tinte di stato e anelli di focus del design system.
      opacity: {
        8: '0.08',
        16: '0.16',
        24: '0.24',
        32: '0.32',
        disabled: '0.64',
      },
      spacing: {
        topbar: 'var(--topbar-height)',
        sidebar: 'var(--sidebar-width)',
      },
      transitionTimingFunction: {
        sheet: 'cubic-bezier(0.32, 0.72, 0, 1)',
      },
      zIndex: {
        sheet: '46',
      },
    },
  },
  plugins: [
    // Dispositivi touch (iPad, telefono): puntatore grossolano. È una variante e
    // non uno `screen` raw: in Tailwind 3 uno screen raw disattiva tutte le
    // varianti `max-*` (`max-lg:`, `max-sm:`).
    ({ addVariant }) => addVariant('coarse', '@media (pointer: coarse)'),
  ],
};
