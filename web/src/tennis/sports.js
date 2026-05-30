// Виды спорта с ракеткой. Должно совпадать с steward/tennis/engine.py (SPORTS).
// Счёт партии одинаковый (PAR до 11, разница ≥2); отличается правило подачи.
export const SPORTS = {
  table_tennis: {
    key: 'table_tennis',
    label: 'Настольный теннис',
    labelShort: 'Теннис',
    emoji: '🏓',
    // победитель партии подаёт следующую? нет — подача по serve_streak
    winnerServes: false,
    accent: 'rose',
  },
  squash: {
    key: 'squash',
    label: 'Сквош',
    labelShort: 'Сквош',
    emoji: '🎾',
    winnerServes: true,
    accent: 'lime',
  },
}

export const DEFAULT_SPORT = 'table_tennis'

export function sportMeta(sport) {
  return SPORTS[sport] || SPORTS[DEFAULT_SPORT]
}

export const SPORT_LIST = Object.values(SPORTS)
