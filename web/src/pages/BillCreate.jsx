import { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronLeft, Plus, X, Users, Mic, Square, Image as ImageIcon,
  Type, Sparkles, Loader2,
} from 'lucide-react'
import { api } from '../api/client'

// Создание счёта с нуля прямо в мини-аппе: шаг «люди» (окружение + вручную) →
// шаг «позиции» (голос/фото/текст → AI-разбор) → доска распределения.

function pickAudioMime() {
  if (typeof MediaRecorder === 'undefined') return null
  const prefs = ['audio/ogg;codecs=opus', 'audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  for (const m of prefs) {
    try { if (MediaRecorder.isTypeSupported(m)) return m } catch { /* noop */ }
  }
  return ''
}

// ── Step 1: люди ──────────────────────────────────────────────────────────────

function PeopleStep({ onCancel, onNext }) {
  const [name, setName] = useState('')
  const [circle, setCircle] = useState([])
  const [selected, setSelected] = useState(() => new Set())
  const [manual, setManual] = useState([])
  const [manualRaw, setManualRaw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/api/bills/circle')
      .then((d) => setCircle(d.people || []))
      .catch(() => { /* окружение не критично */ })
  }, [])

  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const addManual = () => {
    const raw = manualRaw.trim()
    if (!raw) return
    if (!manual.includes(raw)) setManual((m) => [...m, raw])
    setManualRaw('')
  }

  const submit = async () => {
    setError(null)
    if (!name.trim()) { setError('Дай счёту название'); return }
    const participants = [
      ...[...selected].map((id) => ({ person_id: id })),
      ...manual.map((raw) => (raw.startsWith('@') ? { username: raw } : { name: raw })),
    ]
    setBusy(true)
    try {
      const bill = await api.post('/api/bills', {
        name: name.trim(), draft: true, participants,
      })
      onNext(bill)
    } catch (e) {
      setError(e.message || 'Не удалось создать счёт')
    } finally {
      setBusy(false)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} className="px-4 pt-6 pb-4">
      <div className="flex items-center gap-2 mb-5">
        <button onClick={onCancel} className="text-spotify-text hover:text-white p-1 -ml-1"><ChevronLeft size={22} /></button>
        <h1 className="font-display text-2xl font-extrabold text-white">Новый счёт</h1>
      </div>

      <input
        autoFocus
        placeholder="Название счёта…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-full rounded-xl bg-spotify-gray px-4 py-3 text-white text-base outline-none focus:ring-2 focus:ring-gold/50 transition mb-5"
      />

      <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-spotify-text mb-2">
        <Users size={14} /> Кто участвует
      </div>

      {circle.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {circle.slice(0, 24).map((p) => {
            const active = selected.has(p.id)
            return (
              <motion.button
                key={p.id}
                whileTap={{ scale: 0.94 }}
                onClick={() => toggle(p.id)}
                className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                  active
                    ? 'bg-gold text-black border-gold font-medium'
                    : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                }`}
              >
                {p.name}
                {p.count > 0 && <span className="ml-1 text-[10px] opacity-60">·{p.count}</span>}
              </motion.button>
            )
          })}
        </div>
      )}

      <AnimatePresence>
        {manual.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            className="flex flex-wrap gap-2 mb-3"
          >
            {manual.map((raw) => (
              <span key={raw} className="px-3 py-1.5 rounded-full text-sm bg-indigo-soft border border-indigo/50 text-indigo inline-flex items-center gap-1">
                {raw}
                <button onClick={() => setManual((m) => m.filter((x) => x !== raw))} className="opacity-70 hover:opacity-100"><X size={13} /></button>
              </span>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex gap-2 mb-2">
        <input
          placeholder="Имя или @username…"
          value={manualRaw}
          onChange={(e) => setManualRaw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addManual()}
          className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/60 outline-none focus:bg-white/10 transition"
        />
        <button onClick={addManual} className="px-3 rounded-lg bg-white/5 text-spotify-text hover:bg-white/10 transition"><Plus size={18} /></button>
      </div>
      <p className="text-spotify-text/70 text-[11px] mb-5">Ты уже добавлен. Раскидывать позиции по людям будешь на следующем экране.</p>

      {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={submit}
        disabled={busy}
        className="w-full rounded-2xl py-4 font-bold text-base bg-gold text-black disabled:opacity-60 inline-flex items-center justify-center gap-2"
      >
        {busy ? <Loader2 size={18} className="animate-spin" /> : <>Дальше — позиции <ChevronLeft size={18} className="rotate-180" /></>}
      </motion.button>
    </motion.div>
  )
}

// ── Step 2: позиции ───────────────────────────────────────────────────────────

const KIND_LABEL = { 'Текст': Type, 'Фото': ImageIcon, 'Голосовое': Mic }

function contextKind(chunk) {
  const m = /^\[(Текст|Фото|Голосовое)\]/.exec(chunk || '')
  return m ? m[1] : 'Текст'
}

const UNKNOWN_PID = '__unknown__'

function PositionsStep({ bill, onBack, onReady }) {
  const [chunks, setChunks] = useState(() => bill.collection_context || [])
  const [positions, setPositions] = useState(() => bill.transactions || [])
  const [participantIds, setParticipantIds] = useState(() => bill.participants || [])
  const [namesById, setNamesById] = useState({})
  const [payerId, setPayerId] = useState(() => bill.author_person_id)
  const [textVal, setTextVal] = useState('')
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [uploading, setUploading] = useState(null) // 'Фото' | 'Голосовое' | 'Текст'
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState(null)
  const [questions, setQuestions] = useState([])

  const recRef = useRef(null)
  const streamRef = useRef(null)
  const fileRef = useRef(null)
  const timerRef = useRef(null)

  const loadNames = useCallback(async () => {
    try {
      const persons = await api.get('/api/bills/persons')
      setNamesById(Object.fromEntries((persons || []).map((p) => [p.id, p.display_name])))
    } catch { /* имена не критичны */ }
  }, [])

  useEffect(() => { loadNames() }, [loadNames])

  // Назначить одного плательщика на весь счёт (creditor всех позиций).
  const applyPayer = useCallback(async (pid) => {
    setPayerId(pid)
    try {
      const updated = await api.put(`/api/bills/${bill.id}/creditor`, { person_id: pid })
      setPositions(updated.transactions || [])
      setParticipantIds(updated.participants || [])
    } catch (e) {
      setError(e.message || 'Не удалось назначить плательщика')
    }
  }, [bill.id])

  const post = useCallback(async (fd) => {
    const data = await api.post(`/api/bills/${bill.id}/collect`, fd)
    setChunks((c) => [...c, data.recognized
      ? `[${data.kind === 'photo' ? 'Фото' : data.kind === 'voice' ? 'Голосовое' : 'Текст'}]\n${data.recognized}`
      : `[?]`])
    return data
  }, [bill.id])

  const addText = async () => {
    const v = textVal.trim()
    if (!v) return
    setError(null); setUploading('Текст')
    const fd = new FormData()
    fd.append('kind', 'text')
    fd.append('text', v)
    try { await post(fd); setTextVal('') }
    catch (e) { setError(e.message || 'Не вышло') }
    finally { setUploading(null) }
  }

  const onPhoto = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null); setUploading('Фото')
    const fd = new FormData()
    fd.append('kind', 'photo')
    fd.append('file', file, file.name || 'photo.jpg')
    try { await post(fd) }
    catch (err) { setError(err.message || 'Не удалось распознать фото') }
    finally { setUploading(null) }
  }

  const uploadVoice = async (blob, ext) => {
    setError(null); setUploading('Голосовое')
    const fd = new FormData()
    fd.append('kind', 'voice')
    fd.append('file', blob, `voice.${ext}`)
    try { await post(fd) }
    catch (err) { setError(err.message || 'Речь не распознана') }
    finally { setUploading(null) }
  }

  const startRec = async () => {
    setError(null)
    const mime = pickAudioMime()
    if (mime === null || !navigator.mediaDevices?.getUserMedia) {
      // нет MediaRecorder — даём приложить готовый аудиофайл
      fileRef.current?.click()
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const mr = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const parts = []
      mr.ondataavailable = (ev) => ev.data.size && parts.push(ev.data)
      mr.onstop = () => {
        const type = mr.mimeType || 'audio/webm'
        const ext = type.includes('ogg') ? 'ogg' : type.includes('mp4') ? 'm4a' : 'webm'
        uploadVoice(new Blob(parts, { type }), ext)
        streamRef.current?.getTracks().forEach((t) => t.stop())
        streamRef.current = null
      }
      recRef.current = mr
      mr.start()
      setRecording(true)
      setSeconds(0)
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch {
      setError('Нет доступа к микрофону — приложи аудиофайл')
      fileRef.current?.click()
    }
  }

  const stopRec = () => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    setRecording(false)
    try { recRef.current?.stop() } catch { /* noop */ }
  }

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current)
    streamRef.current?.getTracks().forEach((t) => t.stop())
  }, [])

  const onAudioFile = (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const ext = (file.name.split('.').pop() || 'ogg').toLowerCase()
    uploadVoice(file, ext)
  }

  const runParse = async () => {
    setError(null); setParsing(true); setQuestions([])
    try {
      const data = await api.post(`/api/bills/${bill.id}/parse`, {})
      const txs = data.bill?.transactions || []
      setPositions(txs)
      setParticipantIds(data.bill?.participants || [])
      setQuestions(data.questions || [])
      await loadNames()
      // Кто платил: если AI распознал плательщика из голоса/текста — берём его
      // (доминирующий по позициям), иначе остаёмся на авторе. Один на весь счёт.
      const counts = {}
      for (const t of txs) {
        if (t.creditor && t.creditor !== UNKNOWN_PID) counts[t.creditor] = (counts[t.creditor] || 0) + 1
      }
      const detected = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0]
      await applyPayer(detected || payerId || bill.author_person_id)
    } catch (e) {
      // 422 с вопросами — покажем подсказку
      setError(e.message || 'Не нашёл позиций — добавь ещё контекста')
    } finally {
      setParsing(false)
    }
  }

  const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(1, '0')}:${String(s % 60).padStart(2, '0')}`

  return (
    <motion.div initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }} className="px-4 pt-6 pb-4">
      <div className="flex items-center gap-2 mb-1">
        <button onClick={onBack} className="text-spotify-text hover:text-white p-1 -ml-1"><ChevronLeft size={22} /></button>
        <h1 className="font-display text-2xl font-extrabold text-white truncate">{bill.name}</h1>
      </div>
      <p className="text-spotify-text text-sm mb-5 pl-8">Надиктуй, сфоткай чек или впиши позиции</p>

      {/* собранные куски контекста */}
      <AnimatePresence>
        {chunks.length > 0 && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="flex flex-wrap gap-2 mb-4"
          >
            {chunks.map((c, i) => {
              const k = contextKind(c)
              const Icon = KIND_LABEL[k] || Type
              return (
                <motion.span
                  key={i}
                  initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  className="px-3 py-1.5 rounded-full text-xs bg-spotify-green/15 border border-spotify-green/30 text-spotify-green inline-flex items-center gap-1.5"
                >
                  <Icon size={12} /> {k}
                </motion.span>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>

      {/* ввод: текст */}
      <div className="flex gap-2 mb-3">
        <input
          placeholder="Например: пицца 30, кола 5, платил я…"
          value={textVal}
          onChange={(e) => setTextVal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && addText()}
          className="flex-1 rounded-lg bg-white/5 px-3 py-2.5 text-sm text-white placeholder:text-spotify-text/60 outline-none focus:bg-white/10 transition"
        />
        <button onClick={addText} disabled={!textVal.trim() || uploading === 'Текст'} className="px-3 rounded-lg bg-white/5 text-spotify-text hover:bg-white/10 disabled:opacity-50 transition">
          {uploading === 'Текст' ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
        </button>
      </div>

      {/* ввод: фото + голос */}
      <div className="grid grid-cols-2 gap-2 mb-5">
        <button
          onClick={() => document.getElementById('bill-photo-input')?.click()}
          disabled={!!uploading}
          className="rounded-xl bg-white/5 hover:bg-white/10 py-3 text-sm text-white inline-flex items-center justify-center gap-2 disabled:opacity-50 transition"
        >
          {uploading === 'Фото' ? <Loader2 size={16} className="animate-spin" /> : <ImageIcon size={16} />} Фото чека
        </button>
        <input id="bill-photo-input" type="file" accept="image/*" className="hidden" onChange={onPhoto} />
        <input ref={fileRef} type="file" accept="audio/*" className="hidden" onChange={onAudioFile} />

        {!recording ? (
          <button
            onClick={startRec}
            disabled={!!uploading}
            className="rounded-xl bg-gold/15 hover:bg-gold/25 border border-gold/40 py-3 text-sm text-gold inline-flex items-center justify-center gap-2 disabled:opacity-50 transition"
          >
            {uploading === 'Голосовое' ? <Loader2 size={16} className="animate-spin" /> : <Mic size={16} />} Записать голос
          </button>
        ) : (
          <motion.button
            onClick={stopRec}
            initial={{ scale: 0.96 }}
            animate={{ scale: [1, 1.04, 1] }}
            transition={{ repeat: Infinity, duration: 1.1 }}
            className="rounded-xl bg-red-500/20 border border-red-500/50 py-3 text-sm text-red-300 inline-flex items-center justify-center gap-2"
          >
            <Square size={14} className="fill-current" /> Стоп · {fmtTime(seconds)}
          </motion.button>
        )}
      </div>

      {error && <div className="text-red-400 text-sm mb-3">{error}</div>}

      {/* распознать */}
      <motion.button
        whileTap={{ scale: 0.98 }}
        onClick={runParse}
        disabled={parsing || chunks.length === 0}
        className="w-full rounded-2xl py-3.5 font-bold text-base bg-indigo text-white disabled:opacity-50 inline-flex items-center justify-center gap-2 mb-4"
      >
        {parsing ? <><Loader2 size={18} className="animate-spin" /> Разбираю…</> : <><Sparkles size={18} /> Распознать позиции</>}
      </motion.button>

      {questions.length > 0 && (
        <div className="mb-4 rounded-xl bg-yellow-500/10 border border-yellow-500/25 p-3 text-sm text-yellow-200/90 space-y-1">
          <div className="font-medium">Уточни и допиши контекстом:</div>
          {questions.map((q, i) => <div key={i}>• {q.text}</div>)}
        </div>
      )}

      {/* кто платил — один на весь счёт */}
      <AnimatePresence>
        {positions.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mb-4">
            <div className="text-xs uppercase tracking-wider text-spotify-text mb-2">Кто платил за всё</div>
            <div className="flex flex-wrap gap-2">
              {participantIds.map((pid) => {
                const active = payerId === pid
                return (
                  <motion.button
                    key={pid}
                    whileTap={{ scale: 0.94 }}
                    onClick={() => applyPayer(pid)}
                    className={`px-3 py-1.5 rounded-full text-sm border transition-colors ${
                      active
                        ? 'bg-spotify-green/25 border-spotify-green/60 text-spotify-green font-medium'
                        : 'bg-white/5 border-white/10 text-spotify-text hover:bg-white/10'
                    }`}
                  >
                    {namesById[pid] || '…'}
                  </motion.button>
                )
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* предпросмотр позиций */}
      <AnimatePresence>
        {positions.length > 0 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="space-y-2 mb-5">
            <div className="text-xs uppercase tracking-wider text-spotify-text">Позиции ({positions.length})</div>
            {positions.map((tx) => (
              <div key={tx.id} className="bg-spotify-dark rounded-lg px-3 py-2.5 flex items-center justify-between gap-2">
                <span className="text-white text-sm truncate">{tx.item_name || 'Без названия'}</span>
                <span className="text-spotify-text text-sm whitespace-nowrap tabular-nums">
                  {tx.quantity > 1 ? `${tx.quantity}× ` : ''}{(tx.unit_price_minor / 100).toFixed(2).replace(/\.00$/, '')} {bill.currency === 'BYN' ? 'р' : bill.currency}
                </span>
              </div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {positions.length > 0 && (
        <motion.button
          whileTap={{ scale: 0.98 }}
          onClick={() => onReady(bill.id)}
          className="w-full rounded-2xl py-4 font-bold text-base bg-gold text-black inline-flex items-center justify-center gap-2"
        >
          Распределить по людям <ChevronLeft size={18} className="rotate-180" />
        </motion.button>
      )}
    </motion.div>
  )
}

// ── Wizard ────────────────────────────────────────────────────────────────────

export default function BillCreate({ onCancel, onReady }) {
  const [bill, setBill] = useState(null)
  return (
    <div className="max-w-3xl mx-auto">
      <AnimatePresence mode="wait">
        {!bill ? (
          <PeopleStep key="people" onCancel={onCancel} onNext={setBill} />
        ) : (
          <PositionsStep key="positions" bill={bill} onBack={() => setBill(null)} onReady={onReady} />
        )}
      </AnimatePresence>
    </div>
  )
}
