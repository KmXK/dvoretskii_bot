// Голосовое управление табло через браузерный SpeechRecognition.
// Парсит русские команды в WS-сообщения. Continuous mode — телефон лежит,
// игроки кричат команды с расстояния.

const NUM_WORDS = {
  'ноль': 0, 'один': 1, 'одно': 1, 'одна': 1, 'раз': 1,
  'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
  'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9,
  'десять': 10, 'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13,
  'четырнадцать': 14, 'пятнадцать': 15, 'шестнадцать': 16, 'семнадцать': 17,
  'восемнадцать': 18, 'девятнадцать': 19, 'двадцать': 20,
}

function findNumbers(text) {
  const out = []
  // digits
  for (const m of text.matchAll(/\d+/g)) out.push({ at: m.index, n: parseInt(m[0], 10) })
  // russian words
  const lower = text.toLowerCase()
  for (const [word, n] of Object.entries(NUM_WORDS)) {
    let idx = lower.indexOf(word)
    while (idx !== -1) {
      // целое слово?
      const before = idx === 0 || /\W/.test(lower[idx - 1])
      const after = idx + word.length === lower.length || /\W/.test(lower[idx + word.length])
      if (before && after) out.push({ at: idx, n })
      idx = lower.indexOf(word, idx + 1)
    }
  }
  return out.sort((a, b) => a.at - b.at).map((x) => x.n)
}

function matchPlayerName(text, name) {
  if (!name) return false
  const t = text.toLowerCase()
  const n = name.toLowerCase().replace(/[^а-яё\w]+/g, '')
  if (n.length < 2) return false
  // Падежи: ищем хотя бы первые 3-4 буквы как корень
  const stem = n.slice(0, Math.min(4, Math.max(3, n.length - 2)))
  return t.includes(stem)
}

export function parseVoiceCommand(text, state) {
  const t = text.trim().toLowerCase()
  if (!t) return null

  // отмена / undo
  if (/\b(отмен[аи]?|отмени(?:ть)?|назад|undo|вычеркн)\b/.test(t)) {
    return { type: 'undo' }
  }
  // готовый счёт партии (два числа)
  const nums = findNumbers(t)
  if (nums.length >= 2) {
    const [a, b] = nums.slice(0, 2)
    const hi = Math.max(a, b)
    const lo = Math.min(a, b)
    if (hi >= 11 && hi - lo >= 2) {
      // Определяем чью сторону "a" — большее число обычно у победителя слева
      // Лучше определить по словам "алисе"/"бобу"/имени, но без них — считаем
      // что первый названный = первый игрок (player A).
      return { type: 'finish_party', score_a: a, score_b: b }
    }
  }
  // +1 поинт по имени или по букве
  const nameA = state.player_a_name || ''
  const nameB = state.player_b_name || ''
  const matchedA = matchPlayerName(t, nameA)
  const matchedB = matchPlayerName(t, nameB)
  if (matchedA && !matchedB) return { type: 'point', side: 'a' }
  if (matchedB && !matchedA) return { type: 'point', side: 'b' }
  // «А» / «Б» / «первый» / «второй»
  if (/\b(а|первом[уы]?|первый|первая|левому?|лева)\b/.test(t) && /\b(очк|плюс|один|раз)\b/.test(t)) {
    return { type: 'point', side: 'a' }
  }
  if (/\b(б|второ[мйую]|правому?|права)\b/.test(t) && /\b(очк|плюс|один|раз)\b/.test(t)) {
    return { type: 'point', side: 'b' }
  }
  return null
}

export function createVoiceController({ onCommand, onTranscript, onError } = {}) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) {
    return {
      supported: false,
      start: () => {},
      stop: () => {},
    }
  }
  const rec = new SR()
  rec.lang = 'ru-RU'
  rec.continuous = true
  rec.interimResults = false
  rec.maxAlternatives = 1

  let active = false

  rec.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const r = event.results[i]
      if (!r.isFinal) continue
      const transcript = r[0].transcript
      if (onTranscript) onTranscript(transcript)
      if (onCommand) onCommand(transcript)
    }
  }
  rec.onerror = (e) => {
    if (onError) onError(e.error || 'unknown')
    if (e.error === 'no-speech' || e.error === 'audio-capture' || e.error === 'aborted') {
      // не выключаем — пользователь продолжит
    } else if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      active = false
    }
  }
  rec.onend = () => {
    // continuous=true иногда сам останавливается через 30-60с — авто-рестарт
    if (active) {
      try { rec.start() } catch { /* already running */ }
    }
  }

  return {
    supported: true,
    isActive: () => active,
    start: () => {
      active = true
      try { rec.start() } catch { /* already running */ }
    },
    stop: () => {
      active = false
      try { rec.stop() } catch { /* not running */ }
    },
  }
}
