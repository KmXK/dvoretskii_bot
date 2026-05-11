const json = async (res) => {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return res.json()
}

export const api = {
  config: () => fetch('/api/auth/config', { credentials: 'include' }).then(json),
  me: () => fetch('/api/auth/me', { credentials: 'include' }).then(json),
  loginWebapp: (initData) =>
    fetch('/api/auth/webapp', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData }),
    }).then(json),
  loginWidget: (payload) =>
    fetch('/api/auth/widget', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(json),
  logout: () =>
    fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).then(json),
  listAssets: () => fetch('/api/fuck/assets', { credentials: 'include' }).then(json),
  createAsset: ({ file, annotations, name, scope }) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    fd.append('annotations', JSON.stringify(annotations))
    fd.append('name', name)
    fd.append('scope', scope)
    return fetch('/api/fuck/assets', {
      method: 'POST',
      credentials: 'include',
      body: fd,
    }).then(json)
  },
  deleteAsset: (id) =>
    fetch(`/api/fuck/assets/${id}`, { method: 'DELETE', credentials: 'include' }).then(json),
  patchAsset: (id, patch) =>
    fetch(`/api/fuck/assets/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).then(json),
}
