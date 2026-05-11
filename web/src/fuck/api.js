import { api } from '../api/client'

export const fuckApi = {
  listAssets: () => api.get('/api/fuck/assets'),
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
}
