import { useState, useCallback, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import BackButton from '../components/BackButton'
import Dropdown from '../components/Dropdown'
import { api } from '../api/client'

const TABS = [
  { id: 'exchange', label: '💱 Валюты', color: 'from-amber-500/20 to-amber-900/20' },
  { id: 'translate', label: '🌐 Перевод', color: 'from-blue-500/20 to-blue-900/20' },
  { id: 'timezone', label: '🕐 Время', color: 'from-purple-500/20 to-purple-900/20' },
]

const POPULAR_CURRENCIES = ['USD', 'EUR', 'BYN', 'RUB', 'UAH', 'PLN', 'GBP', 'CNY', 'BTC', 'ETH']

const LANGS = [
  { code: 'ru', label: 'Русский' },
  { code: 'en', label: 'Английский' },
  { code: 'de', label: 'Немецкий' },
  { code: 'fr', label: 'Французский' },
  { code: 'es', label: 'Испанский' },
  { code: 'it', label: 'Итальянский' },
  { code: 'pl', label: 'Польский' },
  { code: 'uk', label: 'Українська' },
  { code: 'be', label: 'Беларуская' },
  { code: 'zh', label: '中文' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
  { code: 'ar', label: 'العربية' },
  { code: 'pt', label: 'Португальский' },
  { code: 'tr', label: 'Турецкий' },
]

function ExchangeTool() {
  const [from, setFrom] = useState('USD')
  const [to, setTo] = useState('BYN')
  const [amount, setAmount] = useState('1')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const convert = useCallback(async () => {
    if (!to || !amount) return
    setLoading(true)
    setError(null)
    try {
      const data = await api.get(`/api/exchange?from=${from}&to=${to}&amount=${amount}`)
      setResult(data)
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [from, to, amount])

  const swap = () => { setFrom(to); setTo(from); setResult(null) }

  return (
    <div className="space-y-4">
      <div className="bg-spotify-dark rounded-xl p-4">
        <label className="text-spotify-text text-xs mb-2 block">Сумма</label>
        <input
          type="number"
          value={amount}
          onChange={e => { setAmount(e.target.value); setResult(null) }}
          className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
            focus:ring-1 focus:ring-spotify-green/50"
          placeholder="1"
          min="0"
          step="any"
        />
      </div>

      <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-end">
        <div className="bg-spotify-dark rounded-xl p-4">
          <label className="text-spotify-text text-xs mb-2 block">Из</label>
          <input
            type="text"
            value={from}
            onChange={e => { setFrom(e.target.value.toUpperCase()); setResult(null) }}
            className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
              focus:ring-1 focus:ring-spotify-green/50 uppercase"
            placeholder="USD"
            maxLength={5}
          />
        </div>
        <button onClick={swap} className="mb-4 p-2 text-spotify-text hover:text-white transition-colors">
          ⇄
        </button>
        <div className="bg-spotify-dark rounded-xl p-4">
          <label className="text-spotify-text text-xs mb-2 block">В</label>
          <input
            type="text"
            value={to}
            onChange={e => { setTo(e.target.value.toUpperCase()); setResult(null) }}
            className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
              focus:ring-1 focus:ring-spotify-green/50 uppercase"
            placeholder="BYN"
            maxLength={5}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {POPULAR_CURRENCIES.map(c => (
          <button
            key={c}
            onClick={() => { if (from === c) setTo(c); else setFrom(c); setResult(null) }}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
              from === c || to === c
                ? 'bg-spotify-green/20 text-spotify-green'
                : 'bg-spotify-gray text-spotify-text hover:text-white'
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      <button
        onClick={convert}
        disabled={loading || !to || !amount}
        className="w-full bg-spotify-green text-black font-semibold py-3 rounded-full
          hover:bg-spotify-green/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
      >
        {loading ? 'Конвертирую...' : 'Конвертировать'}
      </button>

      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-spotify-dark rounded-xl p-5 text-center"
          >
            <p className="text-spotify-text text-xs mb-1">{result.amount} {result.from}</p>
            <p className="text-white text-2xl font-bold">{result.result} {result.to}</p>
            <p className="text-spotify-text text-xs mt-2">Курс: 1 {result.from} = {result.rate} {result.to}</p>
          </motion.div>
        )}
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm text-center"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function TranslateTool() {
  const [text, setText] = useState('')
  const [toLang, setToLang] = useState('en')
  const [fromLang, setFromLang] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const translate = useCallback(async () => {
    if (!text.trim() || !toLang) return
    setLoading(true)
    setError(null)
    try {
      const data = await api.post('/api/translate', {
        text: text.trim(),
        to: toLang,
        from: fromLang || undefined,
      })
      setResult(data)
    } catch (e) {
      setError(e.message)
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [text, toLang, fromLang])

  return (
    <div className="space-y-4">
      <div className="bg-spotify-dark rounded-xl p-4">
        <div className="flex items-center justify-between mb-2 gap-3">
          <label className="text-spotify-text text-xs shrink-0">Исходный язык</label>
          <Dropdown
            value={fromLang}
            onChange={v => setFromLang(v)}
            placeholder="Авто"
            options={[{ value: '', label: 'Авто' }, ...LANGS.map(l => ({ value: l.code, label: l.label }))]}
            compact
            className="w-36"
          />
        </div>
        <textarea
          value={text}
          onChange={e => { setText(e.target.value); setResult(null) }}
          className="w-full bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
            focus:ring-1 focus:ring-spotify-green/50 resize-none"
          rows={4}
          placeholder="Введите текст для перевода..."
        />
      </div>

      <div className="bg-spotify-dark rounded-xl p-4">
        <label className="text-spotify-text text-xs mb-2 block">Целевой язык</label>
        <div className="flex flex-wrap gap-1.5">
          {LANGS.map(l => (
            <button
              key={l.code}
              onClick={() => { setToLang(l.code); setResult(null) }}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
                toLang === l.code
                  ? 'bg-spotify-green/20 text-spotify-green'
                  : 'bg-spotify-gray text-spotify-text hover:text-white'
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={translate}
        disabled={loading || !text.trim() || !toLang}
        className="w-full bg-spotify-green text-black font-semibold py-3 rounded-full
          hover:bg-spotify-green/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all text-sm"
      >
        {loading ? 'Перевожу...' : 'Перевести'}
      </button>

      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-spotify-dark rounded-xl p-4"
          >
            {result.detectedLanguage && (
              <p className="text-spotify-text text-xs mb-2">
                Определён язык: {LANGS.find(l => l.code === result.detectedLanguage)?.label || result.detectedLanguage}
              </p>
            )}
            <p className="text-white text-sm whitespace-pre-wrap">{result.text}</p>
            <button
              onClick={() => navigator.clipboard?.writeText(result.text)}
              className="mt-3 text-spotify-text text-xs hover:text-white transition-colors"
            >
              📋 Копировать
            </button>
          </motion.div>
        )}
        {error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm text-center"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function TimezoneTool() {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [cities, setCities] = useState([])
  const timerRef = useRef(null)

  useEffect(() => {
    api.get('/api/timezone').then(setResult).catch(() => {})
    api.get('/api/timezone/cities').then(setCities).catch(() => {})
  }, [])

  useEffect(() => {
    if (!result) return
    timerRef.current = setInterval(() => {
      const q = query.trim()
      api.get(`/api/timezone${q ? `?query=${encodeURIComponent(q)}` : ''}`)
        .then(d => { if (d) setResult(d) })
        .catch(() => {})
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, [query, result?.label])

  const lookup = useCallback(async (q) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.get(`/api/timezone?query=${encodeURIComponent(q || '')}`)
      setResult(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleSubmit = (e) => {
    e.preventDefault()
    lookup(query)
  }

  const POPULAR_CITIES = ['москва', 'минск', 'киев', 'лондон', 'нью-йорк', 'токио', 'берлин', 'дубай']

  return (
    <div className="space-y-4">
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="bg-spotify-dark rounded-xl p-5 text-center"
          >
            <p className="text-spotify-text text-xs mb-1">{result.label}</p>
            <p className="text-white text-3xl font-bold font-mono tracking-wider">{result.time}</p>
            <p className="text-spotify-text text-xs mt-2">{result.offset}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <form onSubmit={handleSubmit} className="bg-spotify-dark rounded-xl p-4">
        <label className="text-spotify-text text-xs mb-2 block">Город или смещение (напр. +3, москва)</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            className="flex-1 bg-spotify-gray rounded-lg px-3 py-2.5 text-white text-sm outline-none
              focus:ring-1 focus:ring-spotify-green/50"
            placeholder="москва, +3, токио..."
          />
          <button
            type="submit"
            disabled={loading}
            className="bg-spotify-green text-black font-semibold px-4 rounded-lg
              hover:bg-spotify-green/90 disabled:opacity-50 transition-all text-sm shrink-0"
          >
            →
          </button>
        </div>
      </form>

      <div className="flex flex-wrap gap-1.5">
        {POPULAR_CITIES.map(c => (
          <button
            key={c}
            onClick={() => { setQuery(c); lookup(c) }}
            className="px-2.5 py-1 rounded-full text-xs font-medium bg-spotify-gray
              text-spotify-text hover:text-white transition-colors capitalize"
          >
            {c}
          </button>
        ))}
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-3 text-red-400 text-sm text-center">
          {error}
        </div>
      )}
    </div>
  )
}

const TOOL_COMPONENTS = {
  exchange: ExchangeTool,
  translate: TranslateTool,
  timezone: TimezoneTool,
}

export default function ToolsPage() {
  const [tab, setTab] = useState('exchange')
  const ToolComponent = TOOL_COMPONENTS[tab]

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6 pb-4 max-w-3xl mx-auto"
    >
      <BackButton />
      <h1 className="text-2xl font-bold text-white mb-4">Инструменты</h1>

      <div className="flex gap-1 mb-5 bg-spotify-dark rounded-xl p-1">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 py-2.5 rounded-lg text-xs font-medium transition-all ${
              tab === t.id
                ? 'bg-spotify-green text-black'
                : 'text-spotify-text hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -20 }}
          transition={{ duration: 0.15 }}
        >
          <ToolComponent />
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}
