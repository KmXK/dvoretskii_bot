import { api } from '../api/client'

export const tennisApi = {
  listSessions: (limit = 30) => api.get(`/api/tennis/sessions?limit=${limit}`),
  getSession: (id) => api.get(`/api/tennis/sessions/${id}`),
  createSession: (body) => api.post('/api/tennis/sessions', body),
  deleteSession: (id) => api.delete(`/api/tennis/sessions/${id}`),
  deleteMatch: (id, idx) => api.delete(`/api/tennis/sessions/${id}/matches/${idx}`),
  toggleServe: (id) => api.post(`/api/tennis/sessions/${id}/serve`),
  getStats: (userId) => api.get(`/api/tennis/stats${userId ? `?user_id=${userId}` : ''}`),
  listOpponents: () => api.get('/api/tennis/opponents'),
  parseImport: (text) => api.post('/api/tennis/import/parse', { text }),
  commitImport: (text, chatId) => api.post('/api/tennis/import', { text, chat_id: chatId }),
  tts: async (text) => {
    const res = await api.raw('/api/tennis/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (res.status === 204) return null
    if (!res.ok) throw new Error(`tts http ${res.status}`)
    return res.blob()
  },
}
