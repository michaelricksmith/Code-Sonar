/**
 * LegalPage — legal documents for pre-public-launch compliance.
 *
 * Terms of Service and Privacy Policy carry the full founder drafts
 * (pending attorney review). Each page is
 * { title, updated, intro, sections: [{ heading, body[] }] }
 * and the renderer handles the rest. To update a document, edit its
 * entry in the LEGAL_CONTENT map below.
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

/** Full draft texts live here. Keep the DRAFT banner until counsel signs off. */
const LEGAL_CONTENT: Record<LegalPageId, LegalDoc> = {
  terms: {
    title: "Terms of Service",
    updated: "October 2026",
    intro:
      'These Terms of Service ("Terms") govern your use of Code Sonar (the "Service"), operated by [Company legal name — to be provided], a California company ("we," "us"). By creating an account or using the Service, you agree to these Terms.',
    sections: [
      {
        heading: "1. The Service",
        body: [
          "Effective date: [To be decided]",
          "Code Sonar analyzes source code you provide — via connected GitHub repositories or uploads — and reports findings, scores, and suggested fixes. Results are informational; you are responsible for reviewing and testing any changes before applying them to your code.",
        ],
      },
      {
        heading: "2. Eligibility and accounts",
        body: [
          "You must be 13 years or older to create an account.",
          "You must be 18 years or older, or have a parent or legal guardian purchase on your behalf, to buy a paid subscription.",
          "You are responsible for activity under your account and for keeping your credentials confidential.",
          "One account per person unless we approve otherwise. We may suspend accounts that violate these Terms.",
        ],
      },
      {
        heading: "3. Subscriptions and billing",
        body: [
          "Plans and prices. Free ($0), Hobby ($7/month), Plus ($14/month). Prices are in USD, exclusive of any applicable taxes.",
          "Automatic renewal. Paid plans are subscriptions that renew automatically each month until you cancel. By subscribing you authorize us (through our payment processor, Stripe) to charge the plan amount to your payment method each billing cycle.",
          "Required disclosures (California Automatic Renewal Law and similar state laws): before you complete checkout we show, adjacent to the payment button: the recurring amount, the monthly billing frequency, that billing renews automatically until cancelled, and how to cancel. You must separately and affirmatively consent to the auto-renewal terms (a pre-ticked box is not consent). We retain consent records for at least 3 years.",
          "Receipts. After purchase you receive an email receipt containing the renewal terms, the cancellation policy, and a cancellation link.",
          "Cancellation. You may cancel at any time from Account → Billing → Cancel subscription in the app (online signup means online cancellation; no call or email required). Cancellation takes effect at the end of the current paid period; you keep access until then and will not be charged again. We will email a cancellation confirmation. You may also cancel through the Stripe customer portal.",
          "Refunds. [To be decided]",
          "Fee changes. We will email you at least 7–30 days before any price increase. If you do not agree, cancel before the increase takes effect.",
          "Annual reminders. We will send an annual reminder of your subscription, the amount and frequency, and how to cancel.",
        ],
      },
      {
        heading: "4. Your code: license and confidentiality",
        body: [
          "To operate the Service, you grant us a limited, non-exclusive, revocable license to ingest, copy, analyze, and display the code and repositories you connect, solely to provide the Service to you.",
          'No model training. We will not use your code, scan results, or repository contents to train machine-learning or AI models. Sanitized excerpts of scan findings may be sent to our AI provider solely to answer your "Ask Sonar" questions and generate fix prompts you request.',
          "We treat your code as confidential and do not disclose it except to our service providers as needed to operate the Service, or as required by law.",
        ],
      },
      {
        heading: "5. Acceptable use",
        body: [
          "You agree not to: (a) use the Service to analyze code you have no right to access; (b) upload malware or unlawful content; (c) attempt to breach the Service's security or other users' accounts; (d) resell or scrape the Service; (e) misrepresent scan results as a security certification.",
        ],
      },
      {
        heading: "6. Intellectual property",
        body: [
          "The Service, its software, branding, and content are owned by us or our licensors. Your code remains yours.",
        ],
      },
      {
        heading: "7. Copyright / DMCA policy",
        body: [
          "We respect copyright. If you believe content processed by the Service infringes your copyright, send a notice to our designated agent at dmca@codevitals.tech including: (1) identification of the copyrighted work; (2) identification of the infringing material and where it appears; (3) your contact information; (4) a good-faith statement; (5) a statement under penalty of perjury that you are authorized to act; and (6) your physical or electronic signature.",
          "Repeat-infringer policy: we will terminate, in appropriate circumstances, accounts of users who are repeat infringers.",
        ],
      },
      {
        heading: "8. Termination",
        body: [
          "We may suspend or terminate your account for violation of these Terms, fraud, or abuse. You may close your account at any time from account settings; closing your account cancels any paid subscription effective at the end of the paid period.",
        ],
      },
      {
        heading: "9. Disclaimers",
        body: [
          'THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. SCAN RESULTS ARE ADVISORY AND MAY BE INCOMPLETE OR INACCURATE.',
        ],
      },
      {
        heading: "10. Limitation of liability",
        body: [
          "TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE WILL NOT BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR FOR LOSS OF PROFITS, DATA, OR GOODWILL. OUR TOTAL LIABILITY FOR ANY CLAIM WILL NOT EXCEED THE AMOUNTS YOU PAID US IN THE 12 MONTHS BEFORE THE CLAIM AROSE (OR $100 IF YOU PAID NOTHING).",
        ],
      },
      {
        heading: "11. Indemnification",
        body: [
          "You agree to indemnify and hold us harmless from claims arising from your code, your use of the Service, or your violation of these Terms.",
        ],
      },
      {
        heading: "12. Governing law and disputes",
        body: [
          "These Terms are governed by California law, without regard to conflict-of-law rules. [To be decided]",
        ],
      },
      {
        heading: "13. Changes to these Terms",
        body: [
          "We will notify you of material changes by email or in-app notice at least 30 days before they take effect. Continued use after the effective date constitutes acceptance.",
        ],
      },
      {
        heading: "14. Contact",
        body: [
          "[Company legal name — to be provided] · support@codevitals.tech · dmca@codevitals.tech",
        ],
      },
    ],
  },
  privacy: {
    title: "Privacy Policy",
    updated: "October 2026",
    intro:
      'This Privacy Policy describes how Code Sonar ("we," "us," "our"), operated by [Company legal name — to be provided], a California company, collects, uses, discloses, and safeguards personal information when you use the Code Sonar website and our code-scanning service (the "Service"). It is posted conspicuously in our website footer and linked at every point of collection.',
    sections: [
      {
        heading: "1. Notice at collection",
        body: [
          "Effective date: [To be decided]",
          "Last updated: [To be decided]",
          "When you sign up or use the Service, we collect the categories of personal information below for the purposes stated. We do not collect more than is reasonably necessary for those purposes.",
        ],
      },
      {
        heading: "2. Categories of personal information we collect",
        body: [
          "Identifiers: name, email address, GitHub username/ID, Google account ID, profile photo URL. Source: you, and GitHub/Google via OAuth.",
          "Account credentials (server-side only): GitHub and Google OAuth access tokens; session tokens. Source: OAuth providers and our servers (encrypted, never sent to your browser).",
          "Customer records: plan tier (Free/Hobby/Plus), Stripe customer ID, subscription status, scan/question usage counts. Source: you, and Stripe via webhook.",
          "Source code and repository contents: cloned repository files, scan findings, fix prompts you generate. Source: repositories you connect.",
          "Internet/network activity: IP address, browser type, pages visited, scan history you save. Source: collected automatically.",
          "Payment data: handled exclusively by Stripe. We never receive, process, or store your card number. Source: Stripe.",
          "We do not collect precise geolocation, biometric data, health data, or Social Security numbers. Third-party web fonts (Google Fonts) may receive your IP address and browser user agent when pages load; no other third-party advertising or tracking technology is used.",
        ],
      },
      {
        heading: "3. How we use personal information",
        body: [
          "Provide, operate, and secure the Service (authentication, repository scanning, displaying results).",
          "Process subscriptions and enforce plan quotas (via Stripe).",
          'Answer "Ask Sonar" questions using sanitized scan context sent to our AI provider.',
          "Communicate with you about your account, security, and billing (transactional messages).",
          "Send product news and marketing only if you separately opt in.",
          "Prevent fraud and abuse, and comply with legal obligations.",
        ],
      },
      {
        heading: "4. Retention",
        body: [
          "Scanned repository contents: deleted after analysis completes, unless you save results to scan history [TBD — founder to provide: confirm deletion cadence].",
          "Saved scan results: retained until you delete them or close your account.",
          "OAuth tokens: retained until you revoke access or close your account; encrypted at rest (AES-GCM).",
          "Account identifiers (name, email): retained for the life of the account, deleted within 90 days of account closure.",
          "Billing records: 7 years (tax and accounting compliance).",
          "Server logs: 90 days.",
        ],
      },
      {
        heading: "5. Disclosure of personal information",
        body: [
          "We disclose personal information only to the following service providers/processors, under written data-processing agreements, and only as needed to operate the Service:",
          "Render (hosting and PostgreSQL database).",
          "Stripe, Inc. (payment processing; subject to Stripe's own privacy policy).",
          "Groq (our AI provider for Ask Sonar; receives only sanitized scan context, not raw repository contents beyond what is needed to answer).",
          "GitHub / Google (OAuth authentication).",
          "We do not sell your personal information. We do not share it for cross-context behavioral advertising. We do not use your code to train machine-learning models — see our Terms of Service.",
        ],
      },
      {
        heading: "6. Your privacy rights",
        body: [
          "Depending on your state of residence, you may have the right to: know what personal information we collect, use, and disclose; delete your personal information; correct inaccurate personal information; opt out of any sale or sharing of personal information (we do not sell or share, but we honor the signal anyway); limit use of sensitive personal information (we collect none); and non-discrimination — we will not penalize you for exercising these rights.",
          "How to exercise your rights: email privacy@codevitals.tech or use our privacy-request webform [TBD — founder to provide: create form before launch]. We will respond within 45 days. We may ask you to verify your identity by confirming control of the email address on your account. Authorized agents may submit requests on your behalf with your written permission.",
          'Opt-out signals: we honor Global Privacy Control (GPC) browser signals as an opt-out of any sale or sharing of personal information. If we ever begin selling or sharing personal information, we will add a "Do Not Sell or Share My Personal Information" link in our footer and confirm opt-outs visibly, per California regulations.',
        ],
      },
      {
        heading: "7. Rhode Island notice",
        body: [
          "Rhode Island law requires a privacy notice on commercial websites serving Rhode Island residents regardless of business size. For Rhode Island residents: we collect the categories listed in §2; we share them only with the service providers listed in §5; we do not sell personal information or engage in targeted advertising; you may exercise the rights in §6 by contacting privacy@codevitals.tech.",
        ],
      },
      {
        heading: "8. Children's privacy",
        body: [
          "The Service is not directed to children. You must be 13 or older to create an account and 18 or older (or have a parent or guardian purchase for you) to buy a paid subscription. We do not knowingly collect personal information from children under 13. If we learn that a child under 13 has created an account, we will suspend the account, verify, and delete the associated personal information.",
        ],
      },
      {
        heading: "9. Security",
        body: [
          "We use TLS in transit, AES-GCM encryption for OAuth tokens at rest, least-privilege access, and routine patching and monitoring. No method of transmission or storage is completely secure, and we cannot guarantee absolute security.",
        ],
      },
      {
        heading: "10. International users",
        body: [
          "The Service is operated in the United States. If you use the Service from Canada and opt in to marketing email, your consent is recorded per Canada's anti-spam law (CASL).",
        ],
      },
      {
        heading: "11. Changes to this policy",
        body: [
          'We will post material changes here and update the "Last updated" date. Continued use of the Service after changes take effect constitutes acceptance.',
        ],
      },
      {
        heading: "12. Contact",
        body: [
          "[Company legal name — to be provided]",
          "Email: privacy@codevitals.tech (privacy requests) · support@codevitals.tech",
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
