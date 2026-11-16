/**
 * Centralized Brand Configuration
 *
 * Configurable brand name driven by VITE_BRAND_NAME with a provisional placeholder (Decision D4).
 * Centralizes name, logo, favicon, typography tokens and metadata.
 */

const RAW_NAME = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BRAND_NAME)
  ? import.meta.env.VITE_BRAND_NAME.trim()
  : '';

export const BRAND_PLACEHOLDER = 'MyClipper';

export const brandConfig = {
  name: RAW_NAME || BRAND_PLACEHOLDER,
  displayName: RAW_NAME || BRAND_PLACEHOLDER,
  tagline: 'AI-powered video clips, instantly.',
  placeholder: BRAND_PLACEHOLDER,
  logo: '/logo.svg',
  favicon: '/favicon.svg',
  supportEmail: 'info@openshorts.app',
  githubUrl: 'https://github.com/francisco-gomera/ClipsOpenShorts',
  primaryColor: '#35C9D0',
  tokens: {
    fontBrand: "'Space Grotesk', ui-sans-serif, system-ui, sans-serif",
    fontUi: "'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif",
    fontMono: 'ui-monospace, SFMono-Regular, monospace',
    colors: {
      background: '#101820',
      surface: '#19252D',
      surfaceElevated: '#22323B',
      border: '#30434C',
      primary: '#35C9D0',
      primaryHover: '#53DDE1',
      primarySoft: '#173B40',
      textPrimary: '#F2F7F8',
      textSecondary: '#A5B6BC',
      success: '#55D6A5',
      warning: '#F4BD68',
      error: '#FF777F',
    },
  },
};

export default brandConfig;
