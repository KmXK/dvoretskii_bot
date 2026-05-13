import { api } from '../api/client'

export const fuckApi = {
  listAssets: () => api.get('/api/fuck/assets'),
  getAssetData: (id) => api.get(`/api/fuck/assets/${id}/data`),
  createAsset: ({ file, annotations, name, scope }) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    fd.append('annotations', JSON.stringify(annotations))
    fd.append('name', name)
    fd.append('scope', scope)
    return api.post('/api/fuck/assets', fd)
  },
  deleteAsset: (id) => api.delete(`/api/fuck/assets/${id}`),
  patchAsset: (id, patch) => api.patch(`/api/fuck/assets/${id}`, patch),
  fetchFromUrl: async (url) => {
    const res = await api.raw('/api/fuck/fetch-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    if (!res.ok) {
      let msg = `HTTP ${res.status}`
      try {
        const body = await res.json()
        if (body?.error) msg = body.error
      } catch { /* noop */ }
      throw new Error(msg)
    }
    const blob = await res.blob()
    const filename = res.headers.get('X-Filename') || 'download'
    return new File([blob], filename, { type: blob.type })
  },
}
