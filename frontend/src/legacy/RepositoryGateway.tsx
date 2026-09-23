import type { CSSProperties } from "react";

interface RepositoryGatewayProps {
  repoPath: string;
  onRepoPathChange: (value: string) => void;
  onLocalScan: () => void;
  onOpenGitHub: () => void;
  scanning: boolean;
}

const stars = Array.from({ length: 28 }, (_, index) => ({
  left: `${(index * 37) % 97}%`,
  top: `${(index * 53) % 89}%`,
  delay: `${(index % 7) * 0.4}s`,
  size: `${index % 5 === 0 ? 2 : 1}px`,
}));

export function RepositoryGateway({
  repoPath,
  onRepoPathChange,
  onLocalScan,
  onOpenGitHub,
  scanning,
}: RepositoryGatewayProps) {
  return (
    <section className="cs-gateway" aria-labelledby="gateway-title">
      <div className="cs-gateway-space" aria-hidden="true">
        <div className="cs-gateway-nebula" />
        {stars.map((star, index) => (
          <i
            key={index}
            className="cs-gateway-star"
            style={{
              "--star-left": star.left,
              "--star-top": star.top,
              "--star-delay": star.delay,
              "--star-size": star.size,
            } as CSSProperties}
          />
        ))}
        <div className="cs-gateway-orbit orbit-one" />
        <div className="cs-gateway-orbit orbit-two" />
      </div>

      <div className="cs-gateway-intro">
        <span className="cs-kicker">Repository intelligence starts here</span>
        <h1 id="gateway-title">Turn code health into a signal your team can act on.</h1>
        <p>
          Establish an evidence-backed baseline, see the debt that matters most,
          and use Sonar to move from finding to validated remediation.
        </p>
        <div className="cs-gateway-authority">
          <span>300–850 deterministic score</span>
          <span>Repository evidence</span>
          <span>AI advisory only</span>
        </div>
      </div>

      <div className="cs-gateway-core" aria-hidden="true">
        <div className="cs-gateway-core-ring ring-three" />
        <div className="cs-gateway-core-ring ring-two" />
        <div className="cs-gateway-core-ring ring-one" />
        <div className="cs-gateway-core-center">
          <span>SONAR</span>
          <strong>READY</strong>
        </div>
      </div>

      <div className="cs-gateway-options">
        <article className="cs-gateway-card primary">
          <div className="cs-gateway-card-icon">&gt;_</div>
          <div>
            <span className="cs-kicker">Local development</span>
            <h2>Scan a local checkout</h2>
            <p>Point Code Sonar at a repository already available to the backend runtime.</p>
          </div>
          <label className="cs-gateway-field">
            <span>Repository path</span>
            <input
              value={repoPath}
              onChange={(event) => onRepoPathChange(event.target.value)}
              spellCheck={false}
              placeholder="C:\\path\\to\\repository"
            />
          </label>
          <button
            className="cs-button primary large"
            onClick={onLocalScan}
            disabled={scanning || !repoPath.trim()}
          >
            {scanning ? "Building baseline…" : "Create local baseline"}
          </button>
          <small>Uses the native <code>repo_path</code> scan contract.</small>
        </article>

        <article className="cs-gateway-card">
          <div className="cs-gateway-card-icon github">GH</div>
          <div>
            <span className="cs-kicker">Managed connection</span>
            <h2>Connect with GitHub</h2>
            <p>Use the existing GitHub App workflow to select and monitor an authorized project.</p>
          </div>
          <button className="cs-button ghost large" onClick={onOpenGitHub}>
            Open GitHub projects
          </button>
          <small>Credentials and repository access stay in the backend.</small>
        </article>

        <article className="cs-gateway-card disabled" aria-disabled="true">
          <div className="cs-gateway-card-icon zip">ZIP</div>
          <div>
            <span className="cs-kicker">Planned connector</span>
            <h2>Upload a repository archive</h2>
            <p>Secure ZIP ingestion is not available in this backend yet.</p>
          </div>
          <button className="cs-button ghost large" disabled>
            ZIP upload coming soon
          </button>
          <small>No placeholder upload or unsupported API call is exposed.</small>
        </article>
      </div>
    </section>
  );
}
