import { useCallback, useEffect, useRef, useState } from 'react'

let _ctx = null
let _warmed = false

function getCtx() {
  if (!_ctx) _ctx = new (window.AudioContext || window.webkitAudioContext)()
  return _ctx
}

function warmUp() {
  if (_warmed) return
  _warmed = true
  const ctx = getCtx()
  if (ctx.state === 'suspended') ctx.resume()
  const buf = ctx.createBuffer(1, 1, ctx.sampleRate)
  const src = ctx.createBufferSource()
  src.buffer = buf
  src.connect(ctx.destination)
  src.start()
}

function play(fn) {
  try {
    const ctx = getCtx()
    if (ctx.state === 'suspended') ctx.resume()
    fn(ctx)
  } catch {}
}

const _reverbCache = new Map()

function getReverbBuf(ctx, decay) {
  const key = decay
  if (_reverbCache.has(key)) return _reverbCache.get(key)
  const rate = ctx.sampleRate
  const len = rate * decay
  const buf = ctx.createBuffer(2, len, rate)
  for (let ch = 0; ch < 2; ch++) {
    const d = buf.getChannelData(ch)
    for (let i = 0; i < len; i++) {
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 2.5)
    }
  }
  _reverbCache.set(key, buf)
  return buf
}

function out(ctx, reverb = false, reverbDecay = 1.2) {
  if (!reverb) return ctx.destination
  const conv = ctx.createConvolver()
  conv.buffer = getReverbBuf(ctx, reverbDecay)
  const dry = ctx.createGain()
  const wet = ctx.createGain()
  dry.gain.value = 0.7
  wet.gain.value = 0.35
  dry.connect(ctx.destination)
  wet.connect(conv).connect(ctx.destination)
  const merge = ctx.createGain()
  merge.connect(dry)
  merge.connect(wet)
  return merge
}

function tone(ctx, freq, dur, type = 'sine', vol = 0.15, delay = 0, dest = null) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = type
  osc.frequency.value = freq
  gain.gain.setValueAtTime(vol, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + dur)
  osc.connect(gain).connect(dest || ctx.destination)
  osc.start(ctx.currentTime + delay)
  osc.stop(ctx.currentTime + delay + dur)
}

function sweep(ctx, f1, f2, dur, type = 'sine', vol = 0.1, delay = 0, dest = null) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = type
  osc.frequency.setValueAtTime(f1, ctx.currentTime + delay)
  osc.frequency.exponentialRampToValueAtTime(f2, ctx.currentTime + delay + dur)
  gain.gain.setValueAtTime(vol, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + dur)
  osc.connect(gain).connect(dest || ctx.destination)
  osc.start(ctx.currentTime + delay)
  osc.stop(ctx.currentTime + delay + dur)
}

function noise(ctx, dur, vol = 0.06, delay = 0, filterFreq = 3000, dest = null) {
  const buf = ctx.createBuffer(1, ctx.sampleRate * dur, ctx.sampleRate)
  const data = buf.getChannelData(0)
  for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1)
  const src = ctx.createBufferSource()
  src.buffer = buf
  const gain = ctx.createGain()
  const filter = ctx.createBiquadFilter()
  filter.type = 'bandpass'
  filter.frequency.value = filterFreq
  filter.Q.value = 0.7
  gain.gain.setValueAtTime(vol, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + dur)
  src.connect(filter).connect(gain).connect(dest || ctx.destination)
  src.start(ctx.currentTime + delay)
  src.stop(ctx.currentTime + delay + dur)
}

function chord(ctx, freqs, dur, vol = 0.08, delay = 0, type = 'sine', dest = null) {
  freqs.forEach(f => tone(ctx, f, dur, type, vol / freqs.length, delay, dest))
}

function kick(ctx, delay = 0, dest = null) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.frequency.setValueAtTime(150, ctx.currentTime + delay)
  osc.frequency.exponentialRampToValueAtTime(30, ctx.currentTime + delay + 0.25)
  gain.gain.setValueAtTime(0.25, ctx.currentTime + delay)
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + delay + 0.25)
  osc.connect(gain).connect(dest || ctx.destination)
  osc.start(ctx.currentTime + delay)
  osc.stop(ctx.currentTime + delay + 0.3)
}

const sounds = {
  spin(ctx) {
    const d = out(ctx)
    sweep(ctx, 200, 800, 0.4, 'sawtooth', 0.08, 0, d)
    sweep(ctx, 150, 600, 0.5, 'square', 0.04, 0, d)
    noise(ctx, 0.5, 0.1, 0, 4000, d)
    kick(ctx, 0, d)
    for (let i = 0; i < 6; i++) {
      tone(ctx, 800 + i * 200, 0.03, 'sine', 0.03, i * 0.04, d)
    }
  },

  reelStop(ctx) {
    const d = out(ctx)
    kick(ctx, 0, d)
    tone(ctx, 500, 0.12, 'square', 0.08, 0, d)
    tone(ctx, 750, 0.08, 'sine', 0.06, 0.02, d)
    tone(ctx, 1000, 0.06, 'sine', 0.04, 0.04, d)
    noise(ctx, 0.08, 0.06, 0, 6000, d)
  },

  win(ctx) {
    const d = out(ctx, true, 1.5)
    const melody = [523, 659, 784, 1047, 1319]
    melody.forEach((f, i) => {
      tone(ctx, f, 0.35, 'sine', 0.12, i * 0.1, d)
      tone(ctx, f * 1.5, 0.25, 'triangle', 0.06, i * 0.1 + 0.03, d)
      tone(ctx, f * 0.5, 0.3, 'sine', 0.04, i * 0.1, d)
    })
    chord(ctx, [523, 659, 784], 0.6, 0.1, 0.5, 'sine', d)
    noise(ctx, 0.3, 0.03, 0, 8000, d)
  },

  bigWin(ctx) {
    const d = out(ctx, true, 2.5)
    kick(ctx, 0, d)
    kick(ctx, 0.3, d)
    const fanfare = [523, 659, 784, 1047, 1319, 1568, 2093]
    fanfare.forEach((f, i) => {
      tone(ctx, f, 0.5, 'sine', 0.14, i * 0.12, d)
      tone(ctx, f * 1.5, 0.4, 'triangle', 0.07, i * 0.12 + 0.04, d)
      tone(ctx, f * 2, 0.3, 'sine', 0.04, i * 0.12 + 0.06, d)
      tone(ctx, f * 0.5, 0.4, 'sine', 0.05, i * 0.12, d)
    })
    chord(ctx, [523, 784, 1047, 1319], 1.0, 0.15, 0.85, 'sine', d)
    chord(ctx, [659, 988, 1319, 1568], 0.8, 0.1, 1.2, 'triangle', d)
    for (let i = 0; i < 12; i++) {
      tone(ctx, 2000 + Math.random() * 3000, 0.08, 'sine', 0.03, 0.5 + i * 0.08, d)
    }
    sweep(ctx, 400, 2000, 1.0, 'sawtooth', 0.04, 0, d)
    noise(ctx, 0.6, 0.05, 0.3, 10000, d)
  },

  lose(ctx) {
    const d = out(ctx, true, 1.0)
    tone(ctx, 400, 0.4, 'sine', 0.1, 0, d)
    tone(ctx, 300, 0.5, 'sine', 0.08, 0.2, d)
    tone(ctx, 220, 0.6, 'sine', 0.07, 0.4, d)
    tone(ctx, 180, 0.7, 'triangle', 0.05, 0.5, d)
    sweep(ctx, 500, 150, 0.8, 'sine', 0.06, 0, d)
  },

  coinFlip(ctx) {
    const d = out(ctx, true, 0.8)
    for (let i = 0; i < 12; i++) {
      const speed = 1 - i / 14
      tone(ctx, 3000 + Math.random() * 2000, 0.03, 'sine', 0.07 * speed, i * 0.06 * (1 + i * 0.08), d)
      tone(ctx, 1500 + Math.random() * 500, 0.02, 'triangle', 0.03 * speed, i * 0.06 * (1 + i * 0.08), d)
    }
    sweep(ctx, 1000, 3000, 0.15, 'sine', 0.04, 0, d)
    noise(ctx, 0.15, 0.04, 0, 8000, d)
  },

  coinLand(ctx) {
    const d = out(ctx, true, 1.2)
    kick(ctx, 0, d)
    tone(ctx, 2200, 0.08, 'sine', 0.12, 0, d)
    tone(ctx, 3000, 0.06, 'sine', 0.08, 0.03, d)
    tone(ctx, 1800, 0.1, 'sine', 0.06, 0.06, d)
    tone(ctx, 2500, 0.15, 'triangle', 0.05, 0.08, d)
    for (let i = 0; i < 5; i++) {
      tone(ctx, 4000 - i * 400, 0.04, 'sine', 0.03, 0.1 + i * 0.03, d)
    }
    noise(ctx, 0.12, 0.05, 0.02, 6000, d)
  },

  rouletteSpin(ctx) {
    const d = out(ctx, true, 1.0)
    sweep(ctx, 100, 500, 1.0, 'sawtooth', 0.05, 0, d)
    noise(ctx, 1.2, 0.06, 0, 2000, d)
    for (let i = 0; i < 30; i++) {
      const t = i * 0.03 * (1 + i * 0.01)
      if (t > 1.2) break
      tone(ctx, 1200 + Math.random() * 800, 0.015, 'sine', 0.04 * (1 - t / 1.2), t, d)
    }
    kick(ctx, 0, d)
  },

  rouletteBall(ctx) {
    const d = out(ctx, true, 1.5)
    kick(ctx, 0, d)
    for (let i = 0; i < 6; i++) {
      const t = i * 0.06
      tone(ctx, 3500 - i * 300, 0.05, 'sine', 0.08 - i * 0.01, t, d)
    }
    tone(ctx, 800, 0.3, 'sine', 0.08, 0.3, d)
    tone(ctx, 1200, 0.25, 'triangle', 0.05, 0.35, d)
    noise(ctx, 0.15, 0.06, 0, 5000, d)
  },

  bonus(ctx) {
    const d = out(ctx, true, 2.0)
    kick(ctx, 0, d)
    kick(ctx, 0.35, d)

    const melody = [392, 523, 659, 784, 1047, 1319, 1568]
    melody.forEach((f, i) => {
      tone(ctx, f, 0.45, 'sine', 0.12, i * 0.13, d)
      tone(ctx, f * 1.5, 0.35, 'triangle', 0.06, i * 0.13 + 0.04, d)
      tone(ctx, f * 2, 0.25, 'sine', 0.03, i * 0.13 + 0.06, d)
    })

    chord(ctx, [523, 659, 784, 1047], 1.0, 0.15, 0.9, 'sine', d)
    chord(ctx, [659, 784, 988, 1319], 0.8, 0.1, 1.3, 'triangle', d)

    for (let i = 0; i < 10; i++) {
      tone(ctx, 2000 + Math.random() * 4000, 0.06, 'sine', 0.025, 0.6 + i * 0.1, d)
    }
    sweep(ctx, 300, 1500, 0.9, 'sawtooth', 0.03, 0, d)
    noise(ctx, 0.4, 0.04, 0.5, 10000, d)
  },

  tick(ctx) {
    tone(ctx, 1200, 0.04, 'sine', 0.06)
    tone(ctx, 1800, 0.02, 'sine', 0.03, 0.01)
  },

  rocketLaunch(ctx) {
    const d = out(ctx, true, 1.0)
    sweep(ctx, 60, 250, 1.2, 'sawtooth', 0.07, 0, d)
    sweep(ctx, 200, 1500, 0.6, 'sine', 0.05, 0, d)
    noise(ctx, 0.8, 0.07, 0, 3000, d)
    kick(ctx, 0, d)
    kick(ctx, 0.12, d)
    for (let i = 0; i < 5; i++)
      tone(ctx, 300 + i * 200, 0.15, 'sine', 0.025, i * 0.12, d)
  },

  rocketCrash(ctx) {
    const d = out(ctx, true, 1.5)
    kick(ctx, 0, d)
    kick(ctx, 0.08, d)
    noise(ctx, 0.7, 0.14, 0, 2000, d)
    sweep(ctx, 800, 80, 0.5, 'sawtooth', 0.1, 0, d)
    sweep(ctx, 500, 60, 0.7, 'sine', 0.06, 0.08, d)
    for (let i = 0; i < 8; i++)
      tone(ctx, 80 + Math.random() * 400, 0.12, 'square', 0.025, i * 0.04, d)
  },
}

const MUTE_KEY = 'casino_muted'

export default function useCasinoSounds() {
  const [muted, setMuted] = useState(() => {
    try { return localStorage.getItem(MUTE_KEY) === '1' } catch { return false }
  })
  const mutedRef = useRef(muted)

  useEffect(() => {
    const handler = () => { warmUp(); window.removeEventListener('pointerdown', handler) }
    window.addEventListener('pointerdown', handler, { once: true })
    return () => window.removeEventListener('pointerdown', handler)
  }, [])

  const toggleMute = useCallback(() => {
    setMuted(prev => {
      const next = !prev
      mutedRef.current = next
      try { localStorage.setItem(MUTE_KEY, next ? '1' : '0') } catch {}
      return next
    })
  }, [])

  const s = useCallback((name) => {
    if (mutedRef.current) return
    const fn = sounds[name]
    if (fn) play(fn)
  }, [])

  return { sound: s, muted, toggleMute }
}
