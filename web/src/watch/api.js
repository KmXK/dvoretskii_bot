import { api } from '../api/client'

export const watchApi = {
  // Сгенерировать одноразовый код привязки часов → {code, expires_in}
  startPairing: () => api.post('/api/watch/pair/start'),
  // Список моих привязанных устройств → {devices: [...]}
  listDevices: () => api.get('/api/watch/devices'),
  // Отозвать токен устройства
  revokeDevice: (id) => api.delete(`/api/watch/devices/${id}`),
  // Подтвердить QR-привязку часов (pair_id из отсканированного deep-link)
  approve: (pairId) => api.post('/api/watch/pair/approve', { pair_id: pairId }),
}
