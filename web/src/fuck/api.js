import { api } from '../api/client'

export const fuckApi = {
  listAssets: () => api.get('/api/fuck/assets'),
  createAsset: ({ file, annotations, name, scope }) => {
    const fd = new FormData()
    fd.append('file', file, file.name)
    fd.append('annotations', JSON.stringify(annotations))
    fd.append('name', name)
    fd.append('scope', scope)
    return api.raw('/api/fuck/assets', { method: 'POST', body: fd }).then(async (res) => {
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    })
  },
  deleteAsset: (id) => api.delete(`/api/fuck/assets/${id}`),
  patchAsset: (id, patch) => api.patch(`/api/fuck/assets/${id}`, patch),
}
