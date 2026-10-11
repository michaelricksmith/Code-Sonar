/**
 * Transparent access-token refresh.
 *
 * Access tokens live 15 minutes. When an API call 401s, this tries one
 * refresh (rotating the refresh token) and retries the request once.
 * If the refresh fails the 401 stands and the app signs the user out.
 */

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "same-origin",
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

const originalFetch = window.fetch.bind(window);

window.fetch = async (
  input: RequestInfo | URL,
  init?: RequestInit
): Promise<Response> => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  // Never intercept the refresh call itself or non-API requests.
  if (url.includes("/api/auth/refresh") || !url.includes("/api/")) {
    return originalFetch(input, init);
  }
  const response = await originalFetch(input, init);
  if (response.status !== 401) return response;
  const refreshed = await tryRefresh();
  if (!refreshed) return response;
  return originalFetch(input, init);
};
