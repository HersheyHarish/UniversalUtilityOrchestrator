/**
 * API Client — all requests use relative URLs (e.g. /api/chat).
 * The Vite dev server proxy forwards /api/* to the orchestrator,
 * so the browser never makes a cross-origin request and CORS is a non-issue.
 */

class APIError extends Error {
  constructor(status, message, details) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

async function request(endpoint, options = {}) {
  const url = endpoint; // relative — proxied by Vite dev server
  try {
    const res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
    });

    // Handle standard ok response
    if (res.ok) {
      const data = await res.json();
      console.log(`[API] 200 OK - ${options.method || 'GET'} ${endpoint}`);
      return data;
    }

    // Handle HTTP errors
    let errorData;
    try {
      errorData = await res.json();
    } catch {
      errorData = { error: res.statusText };
    }

    console.error(`[API] ${res.status} Error - ${options.method || 'GET'} ${endpoint}`, errorData);
    throw new APIError(res.status, errorData.error || "Unknown Error", errorData.detail);

  } catch (err) {
    if (err instanceof APIError) {
      throw err;
    }
    console.error(`[API] Network/Unknown Error - ${options.method || 'GET'} ${endpoint}`, err);
    throw new APIError(0, "Network error or server is unreachable.", err.message);
  }
}

export const api = {
  get: (endpoint) => request(endpoint),
  post: (endpoint, body) => request(endpoint, { method: "POST", body: JSON.stringify(body) }),
};
