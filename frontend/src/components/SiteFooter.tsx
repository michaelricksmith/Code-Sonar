/**
 * SiteFooter — conspicuous footer with legal links.
 * "full" for page bottoms (Landing, Pricing, legal pages);
 * "compact" for the authenticated app's sidebar side-foot.
 */

interface SiteFooterProps {
  variant?: "full" | "compact";
}

const LINKS = [
  { label: "Terms", href: "#/legal/terms" },
  { label: "Privacy", href: "#/legal/privacy" },
  { label: "Accessibility", href: "#/legal/accessibility" },
];

export function SiteFooter({ variant = "full" }: SiteFooterProps) {
  if (variant === "compact") {
    return (
      <nav className="site-footer-compact" aria-label="Legal">
        {LINKS.map((l) => (
          <a key={l.href} href={l.href}>
            {l.label}
          </a>
        ))}
        {/* TODO: founder to provide the real contact email */}
        <a href="mailto:contact@example.com">Contact</a>
      </nav>
    );
  }

  return (
    <footer className="site-footer">
      <div className="site-footer-in">
        <div>
          <span className="brand" style={{ fontSize: 15 }}>
            <span className="brand-mark" style={{ width: 26, height: 26 }} />
            Code&nbsp;Sonar
          </span>
          <div className="site-footer-copy">
            © 2026 Michael Smith. We read your code to score it. We never train on it.
          </div>
        </div>
        <nav className="site-footer-links" aria-label="Legal">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href}>
              {l.label}
            </a>
          ))}
          {/* TODO: founder to provide the real contact email */}
          <a href="mailto:contact@example.com">Contact</a>
        </nav>
      </div>
    </footer>
  );
}
