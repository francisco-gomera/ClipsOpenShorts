/**
 * Centralized Brand Configuration
 *
 * Configurable brand name driven by VITE_BRAND_NAME with a provisional placeholder (Decision D4).
 * Centralizes name, logo, favicon, typography tokens and metadata.
 */

const RAW_NAME = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BRAND_NAME)
  ? import.meta.env.VITE_BRAND_NAME.trim()
  : '';

export const BRAND_PLACEHOLDER = 'ClipsOpenShorts';

export const brandConfig = {
  name: RAW_NAME || BRAND_PLACEHOLDER,
  displayName: RAW_NAME || BRAND_PLACEHOLDER,
  tagline: 'Free AI Clip Maker & Clipping Tool, Open Source',
  placeholder: BRAND_PLACEHOLDER,
  logo: '/logo-openshorts.png',
  favicon: '/logo-openshorts.png',
  supportEmail: 'info@openshorts.app',
  githubUrl: 'https://github.com/francisco-gomera/ClipsOpenShorts',
  tokens: {
    fontDisplay: '"Instrument Serif", ui-serif, Georgia, serif',
    fontBody: '"Geist", ui-sans-serif, system-ui, -apple-system, sans-serif',
    fontMono: '"JetBrains Mono", ui-monospace, monospace',
    colors: {
      paper: 'oklch(13% 0.014 265)',
      paper2: 'oklch(16.5% 0.015 265)',
      paper3: 'oklch(20% 0.016 265)',
      ink: 'oklch(96% 0.006 262)',
      ink2: 'oklch(86% 0.01 262)',
      muted: 'oklch(64% 0.012 262)',
      brass: 'oklch(76% 0.17 50)',
      ok: 'oklch(75% 0.11 150)',
      warn: 'oklch(78% 0.14 75)',
      danger: 'oklch(66% 0.18 25)',
    },
  },
};

export default brandConfig;
