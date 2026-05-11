/**
 * Shared API client. Always sends the session cookie (credentials: 'include')
 * so handlers protected by the auth middleware succeed in both miniapp and
 * web modes. Throws on non-2xx with a useful error message.
 *
 * Bodies are encoded based on type:
 *   - undefined / null  → no body, no Content-Type
 *   - FormData          → passed through, browser sets multipart Content-Type
 *   - everything else   → JSON-encoded with application/json
 */

class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function parse(res) {
  if (!res.ok) {
    let body = ''
    try { body = await res.text() } catch { /* noop */ }
    throw new ApiError(res.status, body || res.statusText || `HTTP ${res.status}`)
  }
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

const baseInit = { credentials: 'include' }

function bodyInit(method, body) {
  if (body === undefined || body === null) {
    return { ...baseInit, method }
  }
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return { ...baseInit, method, body }
  }
  return {
    ...baseInit,
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  get: (path) => fetch(path, baseInit).then(parse),
  post: (path, body) => fetch(path, bodyInit('POST', body)).then(parse),
  put: (path, body) => fetch(path, bodyInit('PUT', body)).then(parse),
  patch: (path, body) => fetch(path, bodyInit('PATCH', body)).then(parse),
  delete: (path) => fetch(path, { ...baseInit, method: 'DELETE' }).then(parse),
  raw: (path, init = {}) => fetch(path, { ...baseInit, ...init }),
}

export { ApiError }
