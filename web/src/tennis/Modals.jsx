import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Download, Pencil, Play, Trash2, X } from 'lucide-react'
import { tennisApi } from './api'
import { useConfirmDialog } from './ConfirmDialog'
import { SPORT_LIST, DEFAULT_SPORT, sportMeta } from './sports'

function isValidPartyScore(a, b) {
  if (a === b) return false
  const hi = Math.max(a, b), lo = Math.min(a, b)
  return hi >= 11 && hi - lo >= 2
}

// Универсальная модалка редактирования счёта партии — используется и при
// исправлении ошибочно записанной партии в активной сессии, и в истории.
export function EditMatchSheet({ open, nameA, nameB, initialScoreA, initialScoreB, onSave, onClose }) {
  const [a, setA] = useState(initialScoreA ?? 11)
  const [b, setB] = useState(initialScoreB ?? 7)
  useEffect(() => {
    if (open) {
      setA(initialScoreA ?? 11)
      setB(initialScoreB ?? 7)
    }
  }, [open, initialScoreA, initialScoreB])

  if (!open) return null
  const valid = isValidPartyScore(a, b)
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[55] bg-black/70 backdrop-blur-sm flex items-end justify-center"
      onClick={onClose}
    >
      <motion.div
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 26, stiffness: 280 }}
        className="bg-zinc-900 border-t border-zinc-700 w-full max-w-2xl rounded-t-2xl shadow-2xl"
        style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 14px)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
          <h2 className="text-white font-bold text-lg">Поправить счёт партии</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-white text-3xl leading-none px-2">×</button>
        </div>
        <div className="px-4 py-3">
          {/* Текущий счёт */}
          <div className="flex items-center justify-center mb-4 gap-3">
            <div className="flex-1 text-right">
              <div className="text-rose-300/80 text-xs uppercase tracking-wider mb-1 truncate">{nameA}</div>
              <div className="text-5xl font-black text-white tabular-nums">{a}</div>
            </div>
            <span className="text-3xl text-zinc-500 pb-2">:</span>
            <div className="flex-1">
              <div className="text-sky-300/80 text-xs uppercase tracking-wider mb-1 truncate">{nameB}</div>
              <div className="text-5xl font-black text-white tabular-nums">{b}</div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-3">
            <div className="flex items-center gap-2">
              <button onClick={() => setA((n) => Math.max(0, n - 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">−</button>
              <div className="flex-1 bg-zinc-800 rounded-xl py-2 text-center text-white text-xl font-bold">{a}</div>
              <button onClick={() => setA((n) => Math.min(50, n + 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">+</button>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={() => setB((n) => Math.max(0, n - 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">−</button>
              <div className="flex-1 bg-zinc-800 rounded-xl py-2 text-center text-white text-xl font-bold">{b}</div>
              <button onClick={() => setB((n) => Math.min(50, n + 1))}
                className="w-12 h-12 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-white text-2xl font-bold">+</button>
            </div>
          </div>

          <p className="text-zinc-500 text-[11px] mb-3 text-center">
            Правило: 11+ у победителя, разница ≥2.
          </p>

          <button
            onClick={() => valid && onSave(a, b)}
            disabled={!valid}
            className={`w-full rounded-2xl py-4 font-bold text-lg ${
              valid ? 'bg-gradient-to-br from-emerald-500 to-emerald-700 text-white shadow-lg' : 'bg-zinc-800 text-zinc-500'
            }`}
          >
            {valid ? `✓ Сохранить ${a}:${b}` : `${a}:${b} — нужен валидный счёт`}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

export function SheetShell({ title, onClose, children, maxHeight = '90svh' }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      // z-50: поверх BottomNav (z-40), иначе нижняя кнопка модалки залезет под мобильную навигацию
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-end justify-center"
      onClick={onClose}
    >
      <motion.div
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', damping: 26, stiffness: 280 }}
        className="bg-spotify-gray border-t border-white/10 w-full max-w-2xl rounded-t-2xl shadow-2xl overflow-y-auto"
        style={{
          maxHeight,
          // 14px (зазор) + safe-area-inset-bottom + 56px (высота BottomNav h-14)
          // чтобы submit-кнопки внутри sheet не закрывались мобильным навбаром
          paddingBottom: 'calc(env(safe-area-inset-bottom) + 70px)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-spotify-gray z-10 flex items-center justify-between px-4 py-3 border-b border-white/5">
          <h2 className="font-display text-white font-extrabold text-lg">{title}</h2>
          <button onClick={onClose} className="text-spotify-text hover:text-white transition-colors p-1 -mr-1"><X size={20} /></button>
        </div>
        <div className="px-4 py-3">{children}</div>
      </motion.div>
    </motion.div>
  )
}

// ── NewSessionSheet ───────────────────────────────────────────────────────────

// Компактный выбор игрока: чипсы из общих чатов + ручной ввод @username/id.
function PlayerPicker({ label, opponents, selectedId, customRaw, onPick, onCustom, accent = 'rose' }) {
  const activeCls = accent === 'sky'
    ? 'bg-sky-500/20 border-sky-400/60 text-sky-200'
    : accent === 'indigo'
      ? 'bg-indigo-soft border-indigo/60 text-indigo'
      : 'bg-rose-500/20 border-rose-400/60 text-rose-200'
  return (
    <div className="mb-3">
      <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">{label}</div>
      {opponents.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {opponents.slice(0, 12).map((o) => (
            <motion.button
              key={o.id}
              whileTap={{ scale: 0.95 }}
              onClick={() => onPick(o.id)}
              className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                selectedId === o.id ? activeCls : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
              }`}
            >
              {o.name}
              {o.played_against > 0 && <span className="ml-1 text-[10px] opacity-70">·{o.played_against}</span>}
            </motion.button>
          ))}
        </div>
      )}
      <input
        type="text"
        value={customRaw}
        onChange={(e) => onCustom(e.target.value)}
        placeholder="@username или id"
        className="w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors"
      />
    </div>
  )
}

export function NewSessionSheet({ open, onClose, onCreated }) {
  const [opponents, setOpponents] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [customRaw, setCustomRaw] = useState('')
  const [sport, setSport] = useState(DEFAULT_SPORT)
  const [firstServer, setFirstServer] = useState('a')
  const [serveStreak, setServeStreak] = useState(2)
  // падел (2v2 + теннисный счёт)
  const [partnerId, setPartnerId] = useState(null)
  const [partnerRaw, setPartnerRaw] = useState('')
  const [oppPartnerId, setOppPartnerId] = useState(null)
  const [oppPartnerRaw, setOppPartnerRaw] = useState('')
  const [goldenPoint, setGoldenPoint] = useState(true)
  const [setsToWin, setSetsToWin] = useState(2)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const sportInfo = sportMeta(sport)
  const isPadel = sport === 'padel'

  useEffect(() => {
    if (!open) return
    setError(null)
    tennisApi.listOpponents()
      .then((d) => setOpponents(d.opponents || []))
      .catch((e) => setError(e.message || 'Не вышло загрузить кандидатов'))
  }, [open])

  const submit = async () => {
    setError(null)
    const opponent = selectedId != null ? selectedId : customRaw.trim()
    if (!opponent && opponent !== 0) {
      setError('Выбери оппонента или впиши @username')
      return
    }
    const payload = {
      opponent,
      sport,
      first_server: firstServer,
      serve_streak: serveStreak,
    }
    if (isPadel) {
      const partner = partnerId != null ? partnerId : partnerRaw.trim()
      const oppPartner = oppPartnerId != null ? oppPartnerId : oppPartnerRaw.trim()
      if ((!partner && partner !== 0) || (!oppPartner && oppPartner !== 0)) {
        setError('В паделе нужны напарник и пара соперников')
        return
      }
      payload.partner = partner
      payload.opponent_partner = oppPartner
      payload.golden_point = goldenPoint
      payload.sets_to_win = setsToWin
    }
    setSubmitting(true)
    try {
      const created = await tennisApi.createSession(payload)
      onCreated(created)
    } catch (e) {
      let msg = e.message || 'Ошибка'
      // распарсим JSON-ошибку aiohttp
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* not json */ }
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="Новая сессия" onClose={onClose}>
        <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Вид спорта</div>
        <div className="grid grid-cols-2 gap-2 mb-4">
          {SPORT_LIST.map((sp) => {
            const active = sport === sp.key
            return (
              <motion.button
                key={sp.key}
                whileTap={{ scale: 0.96 }}
                onClick={() => setSport(sp.key)}
                className={`relative py-3 rounded-xl text-base font-semibold border overflow-hidden transition-colors ${
                  active
                    ? 'border-transparent text-spotify-black'
                    : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                }`}
              >
                {active && (
                  <motion.span
                    layoutId="sport-pill"
                    className="absolute inset-0 bg-gradient-to-br from-gold to-gold-2"
                    transition={{ type: 'spring', stiffness: 500, damping: 32 }}
                  />
                )}
                <span className="relative flex items-center justify-center gap-2">
                  <span className="text-xl">{sp.emoji}</span>
                  {sp.labelShort}
                </span>
              </motion.button>
            )
          })}
        </div>

        <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Оппонент</div>
        {opponents.length === 0 ? (
          <p className="text-spotify-text text-sm mb-3">Кандидатов из общих чатов не нашлось — впиши @username вручную.</p>
        ) : (
          <div className="flex flex-wrap gap-2 mb-3">
            {opponents.slice(0, 12).map((o) => (
              <motion.button
                key={o.id}
                whileTap={{ scale: 0.95 }}
                onClick={() => { setSelectedId(o.id); setCustomRaw('') }}
                className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  selectedId === o.id
                    ? 'bg-sky-500/20 border-sky-400/60 text-sky-200'
                    : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                }`}
              >
                {o.name}
                {o.played_against > 0 && (
                  <span className="ml-1 text-[10px] opacity-70">·{o.played_against}</span>
                )}
              </motion.button>
            ))}
          </div>
        )}
        <input
          type="text"
          value={customRaw}
          onChange={(e) => { setCustomRaw(e.target.value); setSelectedId(null) }}
          placeholder={isPadel ? 'Соперник (@username или id)' : '@username или id'}
          className="w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors mb-4"
        />

        <AnimatePresence initial={false}>
          {isPadel && (
            <motion.div
              key="padel-partners"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <PlayerPicker
                label="Мой напарник"
                opponents={opponents}
                selectedId={partnerId}
                customRaw={partnerRaw}
                onPick={(id) => { setPartnerId(id); setPartnerRaw('') }}
                onCustom={(v) => { setPartnerRaw(v); setPartnerId(null) }}
              />
              <PlayerPicker
                label="Напарник соперника"
                accent="sky"
                opponents={opponents}
                selectedId={oppPartnerId}
                customRaw={oppPartnerRaw}
                onPick={(id) => { setOppPartnerId(id); setOppPartnerRaw('') }}
                onCustom={(v) => { setOppPartnerRaw(v); setOppPartnerId(null) }}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Кто подаёт первым</div>
        <div className="grid grid-cols-2 gap-2 mb-4">
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => setFirstServer('a')}
            className={`py-2.5 rounded-lg text-sm font-medium border transition-colors ${
              firstServer === 'a' ? 'bg-rose-500/20 border-rose-400/60 text-rose-200' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
            }`}
          >
            {isPadel ? '🎾 Моя пара' : '🏓 Я'}
          </motion.button>
          <motion.button
            whileTap={{ scale: 0.97 }}
            onClick={() => setFirstServer('b')}
            className={`py-2.5 rounded-lg text-sm font-medium border transition-colors ${
              firstServer === 'b' ? 'bg-sky-500/20 border-sky-400/60 text-sky-200' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
            }`}
          >
            {isPadel ? '🎾 Соперники' : '🏓 Оппонент'}
          </motion.button>
        </div>

        <AnimatePresence initial={false}>
          {isPadel ? (
            <motion.div
              key="padel-config"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">При 40:40</div>
              <div className="grid grid-cols-2 gap-2 mb-4">
                <motion.button
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setGoldenPoint(true)}
                  className={`py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                    goldenPoint ? 'bg-indigo-soft border-indigo/60 text-indigo' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                  }`}
                >
                  🟡 Золотой мяч
                </motion.button>
                <motion.button
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setGoldenPoint(false)}
                  className={`py-2.5 rounded-lg text-sm font-medium border transition-colors ${
                    !goldenPoint ? 'bg-indigo-soft border-indigo/60 text-indigo' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                  }`}
                >
                  ♻️ Преимущество
                </motion.button>
              </div>
              <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Формат матча</div>
              <div className="flex items-center gap-2 mb-4">
                {[{ n: 1, l: '1 сет' }, { n: 2, l: 'До 2 (bo3)' }, { n: 3, l: 'До 3 (bo5)' }].map((o) => (
                  <motion.button
                    key={o.n}
                    whileTap={{ scale: 0.96 }}
                    onClick={() => setSetsToWin(o.n)}
                    className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      setsToWin === o.n ? 'bg-indigo-soft border-indigo/60 text-indigo' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                    }`}
                  >
                    {o.l}
                  </motion.button>
                ))}
              </div>
            </motion.div>
          ) : sportInfo.winnerServes ? (
            <motion.p
              key="winner-serves"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="text-spotify-text text-xs mb-4 bg-white/5 rounded-lg px-3 py-2 overflow-hidden"
            >
              🎾 В сквоше следующую партию подаёт победитель предыдущей — переключать вручную не нужно.
            </motion.p>
          ) : (
            <motion.div
              key="serve-streak"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Партий за одну подачу</div>
              <p className="text-spotify-text/80 text-[11px] mb-2">
                Каждые N партий первая подача переходит к другому игроку.
              </p>
              <div className="flex items-center gap-2 mb-4">
                {[1, 2, 5].map((n) => (
                  <motion.button
                    key={n}
                    whileTap={{ scale: 0.95 }}
                    onClick={() => setServeStreak(n)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      serveStreak === n ? 'bg-rose-500/20 border-rose-400/60 text-rose-200' : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                    }`}
                  >
                    {n}
                  </motion.button>
                ))}
                <input
                  type="number"
                  min={1}
                  value={serveStreak}
                  onChange={(e) => setServeStreak(Math.max(1, parseInt(e.target.value || '1', 10)))}
                  className="w-16 rounded-lg bg-white/5 px-2 py-1.5 text-sm text-white tabular-nums outline-none focus:bg-white/10 transition-colors ml-auto"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}

        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={submit}
          disabled={submitting}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-3.5 font-display font-extrabold text-lg text-spotify-black transition-colors hover:bg-gold-2 disabled:opacity-50"
        >
          <Play size={18} strokeWidth={2.5} fill="currentColor" />
          {submitting ? 'Создаём…' : 'Начать'}
        </motion.button>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── ImportSheet ───────────────────────────────────────────────────────────────

// Позиция каретки в пикселях внутри textarea. Стандартный приём: клонируем
// стили в скрытый div, кладём в него текст до каретки + маркер-span, читаем
// его offsetTop/offsetLeft.
const _MIRROR_PROPS = [
  'direction', 'boxSizing', 'width', 'height', 'overflowX', 'overflowY',
  'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth', 'borderStyle',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'fontStyle', 'fontVariant', 'fontWeight', 'fontStretch', 'fontSize', 'fontSizeAdjust',
  'lineHeight', 'fontFamily', 'textAlign', 'textTransform', 'textIndent',
  'textDecoration', 'letterSpacing', 'wordSpacing', 'tabSize',
]

function getCaretCoordinates(el, position) {
  const div = document.createElement('div')
  const computed = window.getComputedStyle(el)
  const s = div.style
  s.whiteSpace = 'pre-wrap'
  s.wordWrap = 'break-word'
  s.position = 'absolute'
  s.visibility = 'hidden'
  s.top = '0'
  s.left = '-9999px'
  for (const p of _MIRROR_PROPS) s[p] = computed[p]
  document.body.appendChild(div)
  div.textContent = el.value.slice(0, position)
  const marker = document.createElement('span')
  marker.textContent = el.value.slice(position) || '.'
  div.appendChild(marker)
  const top = marker.offsetTop + parseInt(computed.borderTopWidth || '0', 10)
  const left = marker.offsetLeft + parseInt(computed.borderLeftWidth || '0', 10)
  const lineHeight = parseInt(computed.lineHeight || '0', 10) || parseInt(computed.fontSize, 10) * 1.2
  document.body.removeChild(div)
  return { top, left, lineHeight }
}

const IMPORT_EXAMPLE = `2024-05-10 @ivan 5:3
2024-05-12 @ivan 7:2
2024-05-15 @ivan
11:7
11:9
9:11
12:10
2024-05-20 @ivan 4:6`

export function ImportSheet({ open, onClose, onImported }) {
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(null)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [opponents, setOpponents] = useState([])
  const [suggest, setSuggest] = useState(null)   // {start, end, query, highlighted}
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!open) {
      setText('')
      setPreview(null)
      setError(null)
      setSuggest(null)
      return
    }
    // тянем кандидатов для @-автокомплита
    tennisApi.listOpponents()
      .then((d) => setOpponents(d.opponents || []))
      .catch(() => setOpponents([]))
  }, [open])

  // Парсим состояние «пишет @-handle» — ищем последний @ перед кареткой
  const updateSuggest = (newText, caret) => {
    let i = caret - 1
    while (i >= 0 && /[\w_]/.test(newText[i])) i--
    if (i < 0 || newText[i] !== '@') {
      setSuggest(null)
      return
    }
    const start = i
    const end = caret
    if (start > 0 && !/\s/.test(newText[start - 1])) {
      setSuggest(null)
      return
    }
    const query = newText.slice(start + 1, end).toLowerCase()
    const ta = textareaRef.current
    let coords = null
    if (ta) {
      try {
        const c = getCaretCoordinates(ta, end)
        coords = {
          top: c.top + c.lineHeight - ta.scrollTop,
          left: c.left - ta.scrollLeft,
          lineHeight: c.lineHeight,
        }
      } catch { /* ignore */ }
    }
    setSuggest((prev) => ({
      start,
      end,
      query,
      coords,
      highlighted: prev && prev.start === start ? prev.highlighted : 0,
    }))
  }

  const filteredOpponents = useMemo(() => {
    if (!suggest) return []
    const q = suggest.query
    return opponents
      .filter((o) => o.username && o.username.toLowerCase().includes(q))
      .slice(0, 6)
  }, [opponents, suggest])

  const applySuggestion = (opp) => {
    if (!suggest || !opp?.username) return
    const before = text.slice(0, suggest.start)
    const after = text.slice(suggest.end)
    const insert = `@${opp.username}`
    const newText = before + insert + after
    const newCaret = before.length + insert.length
    setText(newText)
    setSuggest(null)
    // вернём фокус и каретку
    window.setTimeout(() => {
      const ta = textareaRef.current
      if (ta) {
        ta.focus()
        ta.setSelectionRange(newCaret, newCaret)
      }
    }, 0)
  }

  const handleTextareaKeyDown = (e) => {
    if (!suggest || filteredOpponents.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSuggest((s) => ({ ...s, highlighted: (s.highlighted + 1) % filteredOpponents.length }))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSuggest((s) => ({ ...s, highlighted: (s.highlighted - 1 + filteredOpponents.length) % filteredOpponents.length }))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      applySuggestion(filteredOpponents[suggest.highlighted])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setSuggest(null)
    }
  }

  const handleTextareaChange = (e) => {
    const v = e.target.value
    setText(v)
    updateSuggest(v, e.target.selectionStart ?? v.length)
  }

  const handleTextareaSelect = (e) => {
    updateSuggest(text, e.target.selectionStart ?? text.length)
  }

  // Live parsing (debounced)
  useEffect(() => {
    if (!open) return
    if (!text.trim()) { setPreview(null); setError(null); return }
    const id = window.setTimeout(async () => {
      setParsing(true)
      try {
        const d = await tennisApi.parseImport(text)
        setPreview(d.entries || [])
        setError(null)
      } catch (e) {
        let msg = e.message || 'Ошибка'
        try {
          const parsed = JSON.parse(msg)
          if (parsed?.error) msg = parsed.error
        } catch { /* */ }
        setError(msg)
        setPreview(null)
      } finally {
        setParsing(false)
      }
    }, 400)
    return () => window.clearTimeout(id)
  }, [text, open])

  const unresolved = useMemo(
    () => preview ? preview.filter((e) => !e.opponent_id) : [],
    [preview]
  )
  const canSubmit = preview && preview.length > 0 && unresolved.length === 0

  const submit = async () => {
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const d = await tennisApi.commitImport(text)
      onImported(d.created || [])
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* */ }
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null
  return (
    <AnimatePresence>
      <SheetShell title="Импорт истории" onClose={onClose}>
        <p className="text-spotify-text text-xs mb-2">
          Формат: «ГГГГ-ММ-ДД @opp» (потом партии 11:7), либо «ГГГГ-ММ-ДД @opp 5:3» для агрегата.
          Пустые строки игнорятся.
        </p>
        <div className="relative">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleTextareaChange}
            onKeyDown={handleTextareaKeyDown}
            onSelect={handleTextareaSelect}
            onClick={handleTextareaSelect}
            onScroll={(e) => { if (suggest) updateSuggest(text, e.target.selectionStart ?? text.length) }}
            onBlur={() => window.setTimeout(() => setSuggest(null), 150)}
            placeholder={IMPORT_EXAMPLE}
            rows={10}
            className="w-full rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/70 outline-none focus:bg-white/10 transition-colors font-mono"
            style={{ minHeight: 220 }}
          />
          {suggest && filteredOpponents.length > 0 && (
            <div
              className="absolute z-20 bg-spotify-dark border border-white/10 rounded-lg shadow-xl overflow-hidden max-h-60 overflow-y-auto min-w-[220px]"
              style={
                suggest.coords
                  ? { top: suggest.coords.top + 2, left: Math.max(4, suggest.coords.left - 8) }
                  : { left: 0, bottom: -4, transform: 'translateY(100%)' }
              }
            >
              <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-spotify-text border-b border-white/5 bg-spotify-gray">
                @{suggest.query || '…'}
              </div>
              {filteredOpponents.map((o, idx) => (
                <button
                  key={o.id}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => applySuggestion(o)}
                  className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors ${
                    idx === suggest.highlighted ? 'bg-white/10' : 'hover:bg-white/5'
                  }`}
                >
                  <span className="font-mono text-rose-300">@{o.username}</span>
                  {o.name && o.name !== o.username && (
                    <span className="text-spotify-text text-xs truncate">{o.name}</span>
                  )}
                  {o.played_against > 0 && (
                    <span className="ml-auto text-[10px] text-spotify-text">·{o.played_against}</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="mt-3 mb-2 text-xs uppercase tracking-wider text-spotify-text flex items-center justify-between">
          <span>Превью</span>
          {parsing && <span className="text-gold normal-case tracking-normal">парсим…</span>}
        </div>
        {error && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}
        {preview && preview.length > 0 && (
          <ul className="space-y-1 mb-3 text-sm">
            {preview.map((e) => (
              <li key={e.line_no} className={`px-2.5 py-1.5 rounded-lg ${e.opponent_id ? 'bg-spotify-dark' : 'bg-red-500/15 border border-red-500/30'}`}>
                <span className="font-mono text-spotify-text text-xs mr-2">L{e.line_no}</span>
                <span className="font-mono text-white/80 text-xs mr-2">{e.date.slice(0, 10)}</span>
                <span className="text-white mr-2">{e.opponent_id ? e.opponent_name : `❓ ${e.opponent_raw}`}</span>
                {e.mode === 'aggregate' ? (
                  <span className="text-spotify-text text-xs tabular-nums">агрегат {e.wins_a}:{e.wins_b}</span>
                ) : (
                  <span className="text-spotify-text text-xs">{e.score_pairs.length} парт.</span>
                )}
              </li>
            ))}
          </ul>
        )}

        {unresolved.length > 0 && (
          <p className="text-gold text-sm mb-3">
            ⚠ {unresolved.length} оппонент(ов) не распознано — поправь @username и пробуй снова.
          </p>
        )}

        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={submit}
          disabled={!canSubmit || submitting}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gold py-3.5 font-display font-extrabold text-spotify-black transition-colors hover:bg-gold-2 disabled:opacity-40 disabled:hover:bg-gold"
        >
          <Download size={18} strokeWidth={2.5} />
          {submitting ? 'Импортируем…' : `Импортировать ${preview?.length ? `(${preview.length})` : ''}`}
        </motion.button>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── SessionDetailsSheet ───────────────────────────────────────────────────────

export function SessionDetailsSheet({ sessionId, currentUserId, open, onClose, onDeleted }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [editIdx, setEditIdx] = useState(null)
  const { confirm, element: confirmEl } = useConfirmDialog()

  useEffect(() => {
    if (!open || !sessionId) return
    setError(null)
    tennisApi.getSession(sessionId)
      .then(setData)
      .catch((e) => setError(e.message || 'Не загрузилось'))
  }, [open, sessionId])

  const handleDeleteMatch = async (idx) => {
    const ok = await confirm({
      title: `Удалить партию #${idx + 1}?`,
      description: 'Партия исчезнет из сессии и статистики.',
      confirmLabel: 'Удалить',
      destructive: true,
    })
    if (!ok) return
    try {
      const updated = await tennisApi.deleteMatch(sessionId, idx)
      setData(updated)
    } catch (e) {
      setError(e.message || 'Ошибка')
    }
  }

  const handleEditMatch = async (a, b) => {
    if (editIdx == null) return
    try {
      const updated = await tennisApi.updateMatch(sessionId, editIdx, a, b)
      setData(updated)
      setEditIdx(null)
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try { const p = JSON.parse(msg); if (p?.error) msg = p.error } catch { /* */ }
      setError(msg)
    }
  }

  const handleDeleteSession = async () => {
    const ok = await confirm({
      title: 'Удалить сессию?',
      description: 'Удалим целиком вместе со всеми партиями. Это нельзя отменить.',
      confirmLabel: 'Удалить',
      destructive: true,
    })
    if (!ok) return
    try {
      await tennisApi.deleteSession(sessionId)
      onDeleted()
    } catch (e) {
      let msg = e.message || 'Ошибка'
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.error) msg = parsed.error
      } catch { /* */ }
      setError(msg)
    }
  }

  if (!open) return null

  return (
    <AnimatePresence>
      <SheetShell title={data ? `Сессия #${data.id}` : 'Сессия'} onClose={onClose}>
        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
        {!data && !error && <p className="text-spotify-text text-sm">Загружаем…</p>}
        {data && (
          <>
            <div className="text-spotify-text text-sm mb-1 flex items-center gap-2">
              <span title={sportMeta(data.sport).label}>{sportMeta(data.sport).emoji}</span>
              <span>{sportMeta(data.sport).label}</span>
              <span className="text-spotify-text/60">·</span>
              <span>{new Date(data.started_at).toLocaleString('ru-RU')}</span>
            </div>
            <div className="font-display text-white text-lg font-extrabold mb-2">
              {data.player_a_name}{' '}
              <span className="tabular-nums">{data.wins[0]}:{data.wins[1]}</span>{' '}
              {data.player_b_name}
            </div>
            <div className="text-spotify-text text-xs mb-4">
              {data.is_aggregate_only ? 'агрегатный импорт' : `${data.matches?.length ?? 0} партий`}
              {data.duration_seconds != null && ` · ${Math.round(data.duration_seconds / 60)} мин`}
              {data.closed_reason && ` · ${data.closed_reason}`}
            </div>

            {data.matches?.length > 0 && (
              <>
                <div className="text-xs uppercase tracking-wider text-spotify-text mb-2 flex items-center justify-between">
                  <span>Партии</span>
                  {!data.can_edit_matches && data.ended_at && (
                    <span className="text-[10px] normal-case text-spotify-text/60">окно правки закрыто</span>
                  )}
                </div>
                <ol className="space-y-1 mb-4">
                  {data.matches.map((m, i) => {
                    const score = (m.score_a != null && m.score_b != null)
                      ? `${m.score_a}:${m.score_b}` : '—'
                    const winnerName = m.winner === 'a' ? data.player_a_name : data.player_b_name
                    const canEdit = data.can_edit_matches
                    return (
                      <li key={i} className="flex items-center justify-between bg-spotify-dark rounded-lg px-3 py-2.5 text-sm">
                        <span className="text-spotify-text w-6">#{i + 1}</span>
                        <span className="font-semibold tabular-nums text-white w-16">{score}</span>
                        <span className="text-spotify-text text-xs flex-1 truncate ml-2">{winnerName}</span>
                        {canEdit && m.score_a != null && (
                          <button
                            onClick={() => setEditIdx(i)}
                            className="text-gold hover:text-gold-2 ml-2 p-1 transition-colors"
                            title="Поправить счёт"
                          >
                            <Pencil size={15} />
                          </button>
                        )}
                        {canEdit && (
                          <button
                            onClick={() => handleDeleteMatch(i)}
                            className="text-red-400 hover:text-red-300 ml-1 p-1 transition-colors"
                            title="Удалить партию"
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </li>
                    )
                  })}
                </ol>
              </>
            )}

            {data.initiator_id === currentUserId && (
              <motion.button
                whileTap={{ scale: 0.98 }}
                onClick={handleDeleteSession}
                className="w-full flex items-center justify-center gap-2 bg-red-500/15 hover:bg-red-500/25 border border-red-500/30 text-red-300 py-2.5 rounded-xl text-sm font-medium transition-colors"
              >
                <Trash2 size={15} /> Удалить сессию целиком
              </motion.button>
            )}
          </>
        )}
        {confirmEl}
        <AnimatePresence>
          {editIdx != null && data?.matches?.[editIdx] && (
            <EditMatchSheet
              open
              nameA={data.player_a_name}
              nameB={data.player_b_name}
              initialScoreA={data.matches[editIdx].score_a}
              initialScoreB={data.matches[editIdx].score_b}
              onSave={handleEditMatch}
              onClose={() => setEditIdx(null)}
            />
          )}
        </AnimatePresence>
      </SheetShell>
    </AnimatePresence>
  )
}

// ── StatsSheet ────────────────────────────────────────────────────────────────

function fmtDuration(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.round(s)}с`
  if (s < 3600) return `${Math.round(s / 60)} мин`
  return `${(s / 3600).toFixed(1)} ч`
}

export function StatsSheet({ open, onClose }) {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  // null = все виды спорта вместе; иначе фильтр по конкретному
  const [sportFilter, setSportFilter] = useState(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setStats(null)
    tennisApi.getStats(undefined, sportFilter || undefined)
      .then(setStats)
      .catch((e) => setError(e.message || 'Не загрузилось'))
  }, [open, sportFilter])

  if (!open) return null
  const filterTabs = [
    { key: null, label: 'Все', emoji: '∑' },
    ...SPORT_LIST.map((sp) => ({ key: sp.key, label: sp.labelShort, emoji: sp.emoji })),
  ]
  return (
    <AnimatePresence>
      <SheetShell title="Моя статистика" onClose={onClose}>
        <div className="flex gap-2 mb-4">
          {filterTabs.map((t) => {
            const active = sportFilter === t.key
            return (
              <motion.button
                key={t.key ?? 'all'}
                whileTap={{ scale: 0.95 }}
                onClick={() => setSportFilter(t.key)}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                  active
                    ? 'bg-gold text-spotify-black border-transparent'
                    : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                }`}
              >
                <span className="mr-1">{t.emoji}</span>{t.label}
              </motion.button>
            )
          })}
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        {!stats && !error && <p className="text-spotify-text text-sm">Загружаем…</p>}
        {stats && (
          <div className="space-y-3">
            {stats.matches === 0 ? (
              <p className="text-spotify-text text-sm">Партий пока нет.</p>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <StatCard label="Сессий" value={stats.sessions} />
                  <StatCard label="Партий" value={stats.matches} />
                  <StatCard label="Победы / Поражения" value={`${stats.wins} / ${stats.losses}`} />
                  <StatCard label="Win-rate" value={`${Math.round(stats.win_rate * 100)}%`} accent />
                  <StatCard label="Серия побед (max)" value={stats.longest_win_streak} />
                  <StatCard label="Партий за сессию (медиана)" value={stats.median_matches_per_session ?? '—'} />
                  <StatCard label="Разница очков (медиана)" value={stats.median_point_diff ?? '—'} />
                  <StatCard label="Партия (медиана)" value={fmtDuration(stats.median_match_duration_s)} />
                </div>
              </>
            )}
          </div>
        )}
      </SheetShell>
    </AnimatePresence>
  )
}

function StatCard({ label, value, accent = false }) {
  return (
    <div className={`rounded-xl px-3 py-3 border ${accent ? 'border-gold/40 bg-gold-soft' : 'border-white/5 bg-spotify-dark'}`}>
      <div className="text-spotify-text text-[10px] uppercase tracking-wider">{label}</div>
      <div className={`font-display text-xl font-extrabold mt-1 tabular-nums ${accent ? 'text-gold' : 'text-white'}`}>{value}</div>
    </div>
  )
}
