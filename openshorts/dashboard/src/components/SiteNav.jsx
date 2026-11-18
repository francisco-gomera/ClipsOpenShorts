// Landing-page navigation — MyClipper Cyan Dark redesign
// Renders the site header on the marketing/landing page.
// Props: className (string) — forwarded to the wrapper element.
import { useState } from 'react';
import { Menu, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { getToken } from '../lib/api';
import { brandConfig } from '../brand.config';

const hasStoredSession = () => {
  try { return !!getToken(); } catch { return false; }
};

// MyClipper logo mark — geometric selection frame with play triangle
function LogoMark({ size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Outer selection frame with open-bracket corners */}
      <path
        d="M6 2H2v4M26 2h4v4M6 30H2v-4M26 30h4v-4"
        stroke="var(--color-primary)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect
        x="4" y="4" width="24" height="24" rx="3"
        stroke="var(--color-primary)"
        strokeWidth="1.5"
        strokeOpacity="0.35"
      />
      {/* Play triangle */}
      <path
        d="M13 11.5l8 4.5-8 4.5V11.5z"
        fill="var(--color-primary)"
      />
    </svg>
  );
}

export default function SiteNav({ className = '' }) {
  const { isSignedIn, loading, billingEnabled } = useAuth();
  const signedIn = isSignedIn || (loading && hasStoredSession());
  const showLogin = loading || billingEnabled;
  const [mobileOpen, setMobileOpen] = useState(false);

  const NAV_LINKS = [
    { href: '#landing', label: 'Inicio' },
    { href: '/en-vivo', label: 'En vivo' },
    { href: '#/pricing', label: 'Precios', hidden: !billingEnabled },
    { href: brandConfig.githubUrl, label: 'GitHub', external: true },
  ].filter(l => !l.hidden);

  return (
    <header
      className={`w-full sticky top-0 z-50 ${className}`}
      style={{
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <div className="max-w-6xl mx-auto px-4 sm:px-6 h-14 sm:h-16 flex items-center justify-between gap-4">
        {/* Logo */}
        <a
          href="#landing"
          className="flex items-center gap-2.5 shrink-0 group"
          aria-label={`${brandConfig.name} home`}
        >
          <LogoMark size={28} />
          <span
            className="text-lg font-semibold leading-none"
            style={{
              fontFamily: 'var(--font-brand)',
              color: 'var(--color-text-primary)',
            }}
          >
            {brandConfig.name}
          </span>
        </a>

        {/* Desktop nav links */}
        <nav className="hidden sm:flex items-center gap-1" aria-label="Site navigation">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              target={link.external ? '_blank' : undefined}
              rel={link.external ? 'noopener noreferrer' : undefined}
              className="px-3 py-2 text-sm rounded-btn transition-colors"
              style={{
                fontFamily: 'var(--font-ui)',
                color: 'var(--color-text-secondary)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = 'var(--color-primary)';
                e.currentTarget.style.background = 'var(--color-primary-soft)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = 'var(--color-text-secondary)';
                e.currentTarget.style.background = '';
              }}
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* Desktop CTA */}
        <div className="hidden sm:flex items-center gap-3 shrink-0">
          {showLogin && !signedIn && (
            <a
              href="#app?login=1"
              className="text-sm px-4 py-2 rounded-btn transition-colors"
              style={{
                fontFamily: 'var(--font-ui)',
                color: 'var(--color-text-secondary)',
                border: '1px solid var(--color-border)',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'var(--color-primary)';
                e.currentTarget.style.color = 'var(--color-primary)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--color-border)';
                e.currentTarget.style.color = 'var(--color-text-secondary)';
              }}
            >
              Log in
            </a>
          )}
          <a
            href="#app"
            className="text-sm px-4 py-2 rounded-btn font-medium transition-colors"
            style={{
              fontFamily: 'var(--font-ui)',
              background: 'var(--color-primary)',
              color: 'var(--color-background)',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-primary-hover)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'var(--color-primary)'; }}
          >
            {signedIn ? 'Abrir app' : 'Comenzar'}
          </a>
        </div>

        {/* Mobile hamburger */}
        <button
          className="sm:hidden p-2 rounded-btn transition-colors"
          style={{ color: 'var(--color-text-secondary)' }}
          aria-label={mobileOpen ? 'Cerrar menú' : 'Abrir menú'}
          aria-expanded={mobileOpen}
          onClick={() => setMobileOpen(v => !v)}
          onMouseEnter={e => { e.currentTarget.style.background = 'var(--color-primary-soft)'; }}
          onMouseLeave={e => { e.currentTarget.style.background = ''; }}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div
          className="sm:hidden border-t animate-fade"
          style={{
            background: 'var(--color-surface)',
            borderColor: 'var(--color-border)',
          }}
        >
          <nav className="px-4 py-3 flex flex-col gap-1" aria-label="Navegación móvil">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                target={link.external ? '_blank' : undefined}
                rel={link.external ? 'noopener noreferrer' : undefined}
                onClick={() => setMobileOpen(false)}
                className="px-3 py-2.5 rounded-btn text-sm transition-colors"
                style={{
                  fontFamily: 'var(--font-ui)',
                  color: 'var(--color-text-secondary)',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.color = 'var(--color-primary)';
                  e.currentTarget.style.background = 'var(--color-primary-soft)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.color = 'var(--color-text-secondary)';
                  e.currentTarget.style.background = '';
                }}
              >
                {link.label}
              </a>
            ))}
            <div className="flex flex-col gap-2 mt-2 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
              {showLogin && !signedIn && (
                <a
                  href="#app?login=1"
                  onClick={() => setMobileOpen(false)}
                  className="text-center text-sm px-4 py-2.5 rounded-btn transition-colors"
                  style={{
                    fontFamily: 'var(--font-ui)',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  Iniciar sesión
                </a>
              )}
              <a
                href="#app"
                onClick={() => setMobileOpen(false)}
                className="text-center text-sm px-4 py-2.5 rounded-btn font-medium transition-colors"
                style={{
                  fontFamily: 'var(--font-ui)',
                  background: 'var(--color-primary)',
                  color: 'var(--color-background)',
                }}
              >
                {signedIn ? 'Abrir app' : 'Comenzar'}
              </a>
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
