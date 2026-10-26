/**
 * ICEFLOW design tokens: the navy / white / ice-blue theme.
 *
 * Every colour is an RGB triplet held in a CSS variable (see src/index.css) and exposed to
 * Tailwind with an alpha placeholder, so `bg-accent/20` and `text-ink-2` keep working and a
 * future theme (high-contrast, projector) is a variable change, not a code change. Brand tokens
 * (navy, white, ice blue, slate) are themed here; data/semantic ramps stay warm.
 *
 * The map canvas cannot read CSS variables, so src/map/palette.ts mirrors the same hues.
 * If you change a colour here, change its twin there.
 */
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ground: token('ground'),
        panel: token('panel'),
        'panel-2': token('panel-2'),
        'panel-3': token('panel-3'),
        hair: token('hair'),
        'hair-2': token('hair-2'),
        ink: token('ink'),
        'ink-2': token('ink-2'),
        'ink-3': token('ink-3'),
        accent: token('accent'),
        'accent-2': token('accent-2'),
        'on-accent': token('on-accent'),
        route: token('route'),
        teal: token('teal'),
        caution: token('caution'),
        warn: token('warn'),
        danger: token('danger'),
        ok: token('ok'),
        violet: token('violet'),
      },
      fontFamily: {
        // Offline-safe stacks: nothing here downloads a font.
        sans: [
          '"Avenir Next"',
          '"Segoe UI Variable Text"',
          '"Segoe UI"',
          'system-ui',
          '-apple-system',
          'Roboto',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
        // Chart-title serif: section titles and headline figures.
        display: ['"Iowan Old Style"', '"Palatino Linotype"', 'Palatino', '"Book Antiqua"', 'Georgia', 'serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'DejaVu Sans Mono', 'monospace'],
      },
      // Floor of 12 px for any text, so nothing is illegible on a projector.
      fontSize: {
        '2xs': ['12px', '16px'],
        xs2: ['13px', '18px'],
        xs: ['13px', '18px'],
      },
      borderRadius: {
        sheet: '18px',
      },
      boxShadow: {
        // Paper-on-paper depth: a hairline contact shadow plus a long, soft ambient one.
        card: '0 1px 2px rgb(var(--c-ink) / 0.06), 0 8px 24px -14px rgb(var(--c-ink) / 0.25)',
        float: '0 2px 4px rgb(var(--c-ink) / 0.08), 0 18px 40px -16px rgb(var(--c-ink) / 0.38)',
      },
      transitionDuration: {
        DEFAULT: '160ms',
      },
    },
  },
  plugins: [],
};
