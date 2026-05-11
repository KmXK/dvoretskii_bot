import WebApp from '@twa-dev/sdk'

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

function authHeaders() {
  const initData = WebApp?.initData
  return initData ? { 'X-Init-Data': initData } : {}
}

const baseInit = () => ({ credentials: 'include', headers: { ...authHeaders() } })

function bodyInit(method, body) {
  if (body === undefined || body === null) {
    return { ...baseInit(), method }
  }
  if (typeof FormData !== 'undefined' && body instanceof FormData) {
    return { ...baseInit(), method, body }
  }
  const base = baseInit()
  return {
    ...base,
    method,
    headers: { ...base.headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  get: (path) => fetch(path, baseInit()).then(parse),
  post: (path, body) => fetch(path, bodyInit('POST', body)).then(parse),
  put: (path, body) => fetch(path, bodyInit('PUT', body)).then(parse),
  patch: (path, body) => fetch(path, bodyInit('PATCH', body)).then(parse),
  delete: (path) => fetch(path, { ...baseInit(), method: 'DELETE' }).then(parse),
  raw: (path, init = {}) => {
    const base = baseInit()
    return fetch(path, {
      ...base,
      ...init,
      headers: { ...base.headers, ...(init.headers || {}) },
    })
  },
}

export { ApiError }
