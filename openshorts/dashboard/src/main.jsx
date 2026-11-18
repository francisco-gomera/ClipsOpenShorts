import { StrictMode, useState, useEffect, lazy, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Landing from './Landing.jsx'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { capture as captureAttribution } from './lib/attribution'
import PricingPage from './components/PricingPage'
import AccountPage from './components/AccountPage'
import LoginModal from './components/LoginModal'
import { readPendingPlan } from './lib/pendingPlan'
import { track } from './lib/analytics'
import { applyConsent } from './lib/consent'
import CookieBanner from './components/CookieBanner'
import { brandConfig } from './brand.config.js'

const App = lazy(() => import('./App.jsx'))
const Legal = lazy(() => import('./Legal.jsx'))
const OAuthConsent = lazy(() => import('./components/OAuthConsent'))

function PageShell({ title, children }) {
  return (
    <div className="min-h-screen bg-background text-text-secondary">
      <header className="h-14 sm:h-16 border-b border-border bg-surface flex items-center justify-between gap-3 px-4 sm:px-6 sticky top-0 z-20">
        <a href="#app" className="font-brand text-lg text-text-primary truncate" style={{ fontFamily: 'var(--font-brand)' }}>{brandConfig.name}</a>
        <a href="#app" className="text-sm text-text-secondary hover:text-text-primary transition-colors shrink-0">← <span className="hidden sm:inline">Back to app</span><span className="sm:hidden">back</span></a>
      </header>
      <main className="p-4 sm:p-6 md:p-8 pb-[max(2rem,env(safe-area-inset-bottom))]">
        {title && <h1 className="text-2xl sm:text-3xl text-text-primary text-center mb-6 sm:mb-10" style={{ fontFamily: 'var(--font-brand)' }}>{title}</h1>}
        {children}
      </main>
    </div>
  );
}

function PricingView() {
  const { isSignedIn, loading } = useAuth();
  // A plan picked on the landing while signed out lands here: ask for the
  // sign-in straight away instead of a second click on the same plan.
  const [showLogin, setShowLogin] = useState(false);
  // Back from Stripe without paying (cancel_url of a checkout opened here):
  // straight to the plans, not the top of the page, and the query dropped so
  // a reload does not count it twice.
  useEffect(() => {
    if (!window.location.hash.includes('checkout=cancel')) { window.scrollTo(0, 0); return; }
    track('CheckoutCanceled', { props: { back_to: 'pricing' } });
    try { window.history.replaceState(null, '', '#/pricing'); } catch (_) { /* ignore */ }
    requestAnimationFrame(() => document.getElementById('pricing-plans')?.scrollIntoView());
  }, []);
  useEffect(() => {
    if (!loading && !isSignedIn && readPendingPlan()) setShowLogin(true);
  }, [loading, isSignedIn]);
  return (
    <PageShell>
      <PricingPage onRequireLogin={() => setShowLogin(true)} />
      {showLogin && <LoginModal onClose={() => setShowLogin(false)} />}
    </PageShell>
  );
}

function AccountView() {
  const { isSignedIn, loading } = useAuth();
  useEffect(() => {
    if (!loading && !isSignedIn) window.location.hash = '#/pricing';
  }, [loading, isSignedIn]);
  return <PageShell><AccountPage /></PageShell>;
}

// Landing spot after an account is erased. Its own view because the session is
// gone: sending the user to #/account would bounce them to pricing with no
// explanation.
function DeletedView() {
  return (
    <div className="min-h-screen bg-background text-text-secondary flex items-center justify-center p-6">
      <div className="max-w-md text-center space-y-4">
        <h1 className="text-2xl sm:text-3xl text-text-primary" style={{ fontFamily: 'var(--font-brand)' }}>Your account is deleted</h1>
        <p className="text-sm text-text-secondary">
          Your projects, clips and transcripts are gone, any subscription is
          cancelled, and your API keys no longer work. We've emailed you a
          confirmation with the details.
        </p>
        <p className="text-sm text-text-secondary">
          You're welcome back any time — signing up again with the same address
          starts a brand-new, empty account.
        </p>
        <a href="#landing" className="btn-ghost px-4 py-2 inline-flex">Back to {brandConfig.name}</a>
      </div>
    </div>
  );
}

function Root() {
  const resolveView = () => {
    const hash = window.location.hash || '';
    if (hash.startsWith('#/auth/')) return 'auth';       // AuthContext consumes then redirects
    if (hash.startsWith('#/oauth/authorize')) return 'oauth';
    if (hash.startsWith('#/account')) return 'account';
    if (hash.startsWith('#/deleted')) return 'deleted';
    if (hash.startsWith('#/pricing')) return 'pricing';
    if (hash === '#legal') return 'legal';
    if (window.location.pathname.replace(/\/$/, '') === '/en-vivo') return 'app';
    // Fase 8: root (bare /) and #app go directly to the dashboard app.
    // Landing is kept at #landing for those who want it, but is no longer the
    // default entry point — this is a self-hosted tool, not a marketing site.
    if (hash === '#landing') return 'landing';
    if (hash === '#app' || hash.startsWith('#app?')) return 'app';
    // Any unrecognised hash (section anchors like #features, #pricing…) also
    // goes to the app rather than the landing.
    return 'app';
  };

  const [view, setView] = useState(resolveView);

  useEffect(() => {
    const handleHashChange = () => setView(resolveView());
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleLaunchApp = () => {
    window.location.hash = '#app';
    setView('app');
  };

  if (view === 'legal') return <Legal />;
  if (view === 'pricing') return <PricingView />;
  if (view === 'account') return <AccountView />;
  if (view === 'oauth') return <OAuthConsent />;
  if (view === 'deleted') return <DeletedView />;
  if (view === 'auth') {
    return <div className="min-h-screen flex items-center justify-center bg-background text-text-secondary text-sm">signing you in…</div>;
  }
  if (view === 'app') return <App />;
  return <Landing onLaunchApp={handleLaunchApp} />;
}

// Before React mounts: AuthContext rewrites the URL on auth redirects, which
// would destroy the referrer and any UTM params we still need to read.
captureAttribution();

// Start whatever the visitor previously agreed to. Nothing at all on a first
// visit: index.html only publishes the analytics initialiser, it never runs it.
applyConsent();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <Suspense fallback={<div className="min-h-screen bg-background flex items-center justify-center text-text-secondary text-sm">
          <div className="flex flex-col items-center gap-4">
            <span className="text-2xl font-brand text-primary" style={{ fontFamily: 'var(--font-brand)' }}>MyClipper</span>
            <svg className="animate-spin text-primary" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a9 9 0 1 1-6.219-8.56" />
            </svg>
          </div>
        </div>}>
        <Root />
      </Suspense>
      <CookieBanner />
    </AuthProvider>
  </StrictMode>,
)
