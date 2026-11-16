import { Github } from 'lucide-react';
import { brandConfig } from '../brand.config';

/**
 * Simplified banner displayed on the landing page.
 * Uses Cyan Dark tokens only.
 */
export default function StarBanner({ message }) {
  const displayMsg = message || `Enjoying ${brandConfig.name}?`;
  return (
    <a
      href={brandConfig.githubUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-2 px-3 py-2 rounded-input bg-surface-elevated border border-border text-xs text-text-secondary hover:text-primary transition-colors"
    >
      <Github size={14} className="shrink-0" />
      <span>{displayMsg} <span className="text-primary">Star on GitHub ⭐</span></span>
    </a>
  );
}
