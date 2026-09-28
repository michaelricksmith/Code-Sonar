/**
 * LegalPage — stub legal documents for pre-public-launch compliance.
 *
 * Every document is a DRAFT under legal review. Full drafts are being
 * written in parallel: to replace a stub, edit the LEGAL_CONTENT map
 * below — each page is { title, updated, sections: [{ heading, body[] }] }
 * and the renderer handles the rest.
 */

import { SiteFooter } from "./SiteFooter";

export type LegalPageId = "terms" | "privacy" | "accessibility";

interface LegalSection {
  heading: string;
  /** Paragraphs; the string "[TBD — founder to provide]" marks placeholders. */
  body: string[];
}

interface LegalDoc {
  title: string;
  updated: string;
  intro: string;
  sections: LegalSection[];
}

/** The single place full drafts will land. Keep stubs to one page each. */
const LEGAL_CONTENT: Record<LegalPageId, LegalDoc> = {
  terms: {
    title: "Terms of Service",
    updated: "September 2026",
    intro:
      "These are the ground rules for using Code Sonar. The short version: be kind to the service, don't abuse it, and know what you're signing up for.",
    sections: [
      {
        heading: "Who can use Code Sonar",
        body: [
          "You must be at least 13 years old to create an account. Paid tiers (Hobby and Plus) require you to be 18 or older, or to have a parent or guardian's permission and payment method.",
          "One account per person. You're responsible for keeping your sign-in credentials safe.",
        ],
      },
      {
        heading: "What you get",
        body: [
          "Code Sonar scores your repositories and explains issues in plain language. Scores are informational — they're a guide for improving your code, not a guarantee of correctness or security.",
          "Free, Hobby ($7/month), and Plus ($14/month) tiers are described on the pricing page. We may adjust limits and features over time and will tell you before changes take effect.",
        ],
      },
      {
        heading: "Cancellation policy",
        body: [
          "Cancel anytime, right in the app — no calls, no emails, no retention gauntlet. Your paid plan stays active until the end of your current billing period, then drops to Free. We don't do partial-month refunds.",
        ],
      },
      {
        heading: "Fair use",
        body: [
          "Don't hammer the scanners, resell scan capacity, or try to break the service. We'll warn you first unless the abuse is egregious.",
        ],
      },
    ],
  },
  privacy: {
    title: "Privacy Policy",
    updated: "September 2026",
    intro:
      "Your code is your business. This policy explains what we collect, why, and what we never do with it.",
    sections: [
      {
        heading: "Our no-sale posture",
        body: [
          "We do not sell your personal information or share it for cross-context behavioral advertising. We honor Global Privacy Control signals.",
        ],
      },
      {
        heading: "What we collect",
        body: [
          "Account basics: name, email, and sign-in provider (GitHub or Google) so you can log in.",
          "Repository code you ask us to scan, so we can compute your score and explain issues. Scan results and your fix activity are kept so you can track progress over time.",
          "Billing details are handled by Stripe — we never see or store your card number.",
          "Product updates and tips emails only if you opt in (you can change this anytime).",
        ],
      },
      {
        heading: "What we don't do",
        body: [
          "We never use your code to train AI models. We don't show your secrets in plain text, and we don't share your data with advertisers.",
        ],
      },
      {
        heading: "Your choices",
        body: [
          "Ask us to export or delete your data anytime — contact privacy@[TBD — founder to provide].",
        ],
      },
    ],
  },
  accessibility: {
    title: "Accessibility Statement",
    updated: "September 2026",
    intro:
      "Code Sonar is built for builders of every kind — including builders who use assistive technology.",
    sections: [
      {
        heading: "Our commitment",
        body: [
          "We aim to make Code Sonar usable by everyone. That means keyboard-navigable pages, visible focus states, labeled controls, and text alternatives where images carry meaning.",
          "This is an ongoing effort, not a one-time checkbox. If something gets in your way, we want to hear about it.",
        ],
      },
      {
        heading: "Contact us",
        body: [
          "Found an accessibility barrier? Email accessibility@[TBD — founder to provide] and we'll dig in.",
        ],
      },
    ],
  },
};

export function LegalPage({ page }: { page: LegalPageId }) {
  const doc = LEGAL_CONTENT[page];
  return (
    <div className="page legal-page">
      <div className="notice warning legal-draft-banner" role="note">
        <b>DRAFT</b>
        These documents are under legal review and will be finalized before public launch.
      </div>
      <p className="page-sub" style={{ marginTop: 18 }}>
        Last updated {doc.updated}
      </p>
      <h1 className="page-title">{doc.title}</h1>
      <p className="page-sub">{doc.intro}</p>
      {doc.sections.map((s) => (
        <section key={s.heading} className="legal-section">
          <h2>{s.heading}</h2>
          {s.body.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
        </section>
      ))}
      <SiteFooter />
    </div>
  );
}
