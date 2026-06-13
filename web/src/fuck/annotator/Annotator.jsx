import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { loadSource } from './sources'

const COLORS = { a: '#ff4a4a', b: '#4ade80' }
const ROT_HANDLE_OFFSET = 24

function lerp(a, b, r) { return a + (b - a) * r }
function kfVisible(k) { return k.visible !== false }
function kfAngle(k) { return k.angle || 0 }
function round(v) { return Math.round(v * 100) / 100 }
function boxAngleRad(b) { return ((b.angle || 0) * Math.PI) / 180 }
function boxCenter(b) { return { x: b.x + b.w / 2, y: b.y + b.h / 2 } }

function interpolate(kfs, t) {
  if (kfs.length === 0) return null
  if (t <= kfs[0].t) {
    const k = kfs[0]
    return { t, x: k.x, y: k.y, w: k.w, h: k.h, angle: kfAngle(k), visible: kfVisible(k) }
  }
  if (t >= kfs[kfs.length - 1].t) {
    const k = kfs[kfs.length - 1]
    return { t, x: k.x, y: k.y, w: k.w, h: k.h, angle: kfAngle(k), visible: kfVisible(k) }
  }
  for (let i = 0; i < kfs.length - 1; i++) {
    if (t >= kfs[i].t && t <= kfs[i + 1].t) {
      const span = kfs[i + 1].t - kfs[i].t
      const r = span > 0 ? (t - kfs[i].t) / span : 0
      return {
        t,
        x: lerp(kfs[i].x, kfs[i + 1].x, r),
        y: lerp(kfs[i].y, kfs[i + 1].y, r),
        w: lerp(kfs[i].w, kfs[i + 1].w, r),
        h: lerp(kfs[i].h, kfs[i + 1].h, r),
        angle: lerp(kfAngle(kfs[i]), kfAngle(kfs[i + 1]), r),
        visible: kfVisible(kfs[i]),
      }
    }
  }
  return null
}

function localToWorld(b, lx, ly) {
  const a = boxAngleRad(b)
  const c = Math.cos(a), s = Math.sin(a)
  const ctr = boxCenter(b)
  return { x: ctr.x + lx * c - ly * s, y: ctr.y + lx * s + ly * c }
}

function worldToLocal(b, wx, wy) {
  const a = -boxAngleRad(b)
  const c = Math.cos(a), s = Math.sin(a)
  const ctr = boxCenter(b)
  const dx = wx - ctr.x, dy = wy - ctr.y
  return { x: dx * c - dy * s, y: dx * s + dy * c }
}

function hitTest(box, x, y) {
  const rot = localToWorld(box, 0, -box.h / 2 - ROT_HANDLE_OFFSET)
  if (Math.hypot(x - rot.x, y - rot.y) < 10) return 'rotate'
  const lp = worldToLocal(box, x, y)
  const hw = box.w / 2, hh = box.h / 2
  const sx = Math.max(3, Math.min(14, box.w / 3))
  const sy = Math.max(3, Math.min(14, box.h / 3))
  if (Math.abs(lp.x) < hw - sx && Math.abs(lp.y) < hh - sy) return 'move'
  const nearX = (xx) => Math.abs(lp.x - xx) < sx
  const nearY = (yy) => Math.abs(lp.y - yy) < sy
  if (nearX(-hw) && nearY(-hh)) return 'nw'
  if (nearX(hw) && nearY(-hh)) return 'ne'
  if (nearX(-hw) && nearY(hh)) return 'sw'
  if (nearX(hw) && nearY(hh)) return 'se'
  if (nearX(0) && nearY(-hh)) return 'n'
  if (nearX(0) && nearY(hh)) return 's'
  if (nearX(-hw) && nearY(0)) return 'w'
  if (nearX(hw) && nearY(0)) return 'e'
  if (lp.x >= -hw && lp.x <= hw && lp.y >= -hh && lp.y <= hh) return 'move'
  return null
}

const Annotator = forwardRef(function Annotator(_props, ref) {
  const canvasRef = useRef(null)
  const timelineRef = useRef(null)
  const sourceRef = useRef(null)
  const keyframesRef = useRef({ a: [], b: [] })
  const bboxRef = useRef({ a: null, b: null })
  const draggingRef = useRef(null)
  const tlDragRef = useRef(false)
  const activeRef = useRef('a')
  const playingRef = useRef(false)

  const [active, setActive] = useState('a')
  const [info, setInfo] = useState('')
  const [size, setSize] = useState({ w: 0, h: 0, angle: 0 })
  const [fps, setFps] = useState(30)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState(null)
  const [loaded, setLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sourceKind, setSourceKind] = useState(null)
  const [duration, setDuration] = useState(0)
  const [playheadRatio, setPlayheadRatio] = useState(0)
  const [keyframeMarkers, setKeyframeMarkers] = useState([])
  const [tlWidth, setTlWidth] = useState(0)

  const keyTolerance = useCallback(() => 1 / (sourceRef.current?.fps || 30) / 2.5, [])

  const findKeyframeAt = useCallback((ch, t) => {
    const tol = keyTolerance()
    return keyframesRef.current[ch].findIndex((k) => Math.abs(k.t - t) < tol)
  }, [keyTolerance])

  const upsertKeyframe = useCallback((ch, box, opts) => {
    if (!box || !sourceRef.current) return
    const t = sourceRef.current.currentTime
    const idx = findKeyframeAt(ch, t)
    const prevVisible = idx >= 0 ? kfVisible(keyframesRef.current[ch][idx]) : true
    const visible = opts && 'visible' in opts ? opts.visible : prevVisible
    const entry = { t, x: round(box.x), y: round(box.y), w: round(box.w), h: round(box.h) }
    const ang = round(box.angle || 0)
    if (ang) entry.angle = ang
    if (!visible) entry.visible = false
    if (idx >= 0) keyframesRef.current[ch][idx] = entry
    else {
      keyframesRef.current[ch].push(entry)
      keyframesRef.current[ch].sort((a, b) => a.t - b.t)
    }
  }, [findKeyframeAt])

  const removeKeyframeAt = useCallback((ch) => {
    if (!sourceRef.current) return
    const idx = findKeyframeAt(ch, sourceRef.current.currentTime)
    if (idx >= 0) keyframesRef.current[ch].splice(idx, 1)
  }, [findKeyframeAt])

  const updateBboxes = useCallback(() => {
    const src = sourceRef.current
    if (!src) return
    for (const ch of ['a', 'b']) {
      if (draggingRef.current && draggingRef.current.ch === ch) continue
      const interp = interpolate(keyframesRef.current[ch], src.currentTime)
      if (interp) bboxRef.current[ch] = interp
      else if (!bboxRef.current[ch]) {
        const w = src.width, h = src.height
        const sz = Math.min(w, h) * 0.18
        bboxRef.current[ch] = {
          x: ch === 'a' ? w * 0.25 - sz / 2 : w * 0.65 - sz / 2,
          y: h * 0.35,
          w: sz, h: sz,
          angle: 0,
        }
      }
    }
  }, [])

  const render = useCallback(() => {
    const src = sourceRef.current
    const canvas = canvasRef.current
    if (!src || !canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    src.draw(ctx)
    updateBboxes()

    for (const ch of ['a', 'b']) {
      const b = bboxRef.current[ch]
      if (!b) continue
      const isActive = ch === activeRef.current
      const isHidden = b.visible === false
      const ctr = boxCenter(b)
      const hw = b.w / 2, hh = b.h / 2
      const diag = Math.sqrt(b.w * b.w + b.h * b.h)

      ctx.save()
      ctx.translate(ctr.x, ctr.y)
      ctx.rotate(boxAngleRad(b))

      ctx.strokeStyle = COLORS[ch]
      ctx.lineWidth = isActive ? 3 : 2
      ctx.globalAlpha = isHidden ? 0.5 : 1
      if (isHidden) ctx.setLineDash([6, 4])
      ctx.strokeRect(-hw, -hh, b.w, b.h)
      ctx.setLineDash([])

      ctx.globalAlpha = isHidden ? 0.25 : 0.4
      ctx.beginPath()
      ctx.arc(0, 0, diag / 2, 0, Math.PI * 2)
      ctx.stroke()
      ctx.globalAlpha = 1

      ctx.fillStyle = COLORS[ch]
      ctx.globalAlpha = isHidden ? 0.5 : 1
      ctx.font = 'bold 14px -apple-system, sans-serif'
      ctx.fillText(ch.toUpperCase() + (isHidden ? ' (hidden)' : ''), -hw + 4, -hh + 16)
      ctx.globalAlpha = 1

      if (isActive) {
        const s = 8
        const handles = [
          [-hw, -hh], [hw, -hh], [-hw, hh], [hw, hh],
          [0, -hh], [0, hh], [-hw, 0], [hw, 0],
        ]
        for (const [px, py] of handles) {
          ctx.fillStyle = COLORS[ch]
          ctx.fillRect(px - s / 2, py - s / 2, s, s)
        }
        ctx.strokeStyle = COLORS[ch]
        ctx.beginPath()
        ctx.moveTo(0, -hh)
        ctx.lineTo(0, -hh - ROT_HANDLE_OFFSET)
        ctx.stroke()
        ctx.fillStyle = COLORS[ch]
        ctx.beginPath()
        ctx.arc(0, -hh - ROT_HANDLE_OFFSET, 6, 0, Math.PI * 2)
        ctx.fill()
      }

      if (findKeyframeAt(ch, src.currentTime) >= 0) {
        ctx.fillStyle = COLORS[ch]
        ctx.beginPath()
        ctx.arc(hw - 7, -hh + 7, 4, 0, Math.PI * 2)
        ctx.fill()
        ctx.fillStyle = '#fff'
        ctx.beginPath()
        ctx.arc(hw - 7, -hh + 7, 1.5, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
    }
    const t = src.currentTime
    const frame = Math.round(t * src.fps)
    setInfo(`t=${t.toFixed(3)}s  frame ${frame}/${src.frames}  fps=${src.fps.toFixed(2)}  A:${keyframesRef.current.a.length} B:${keyframesRef.current.b.length}`)
    const ab = bboxRef.current[activeRef.current]
    if (ab) setSize({ w: Math.round(ab.w), h: Math.round(ab.h), angle: Math.round(ab.angle || 0) })
    setPlayheadRatio(src.duration > 0 ? src.currentTime / src.duration : 0)
    const markers = []
    for (const ch of ['a', 'b']) {
      for (const kf of keyframesRef.current[ch]) markers.push({ ch, t: kf.t })
    }
    setKeyframeMarkers(markers)
  }, [updateBboxes, findKeyframeAt])

  const setActiveCh = useCallback((ch) => {
    activeRef.current = ch
    setActive(ch)
    render()
  }, [render])

  const stepFrame = useCallback(async (delta) => {
    const src = sourceRef.current
    if (!src) return
    if (src.kind === 'gif' || src.kind === 'webp') {
      const idx = src._frameIdxAt(src.currentTime)
      const next = Math.max(0, Math.min(src.frames - 1, idx + delta))
      await src.seek(src.frameData[next].t)
    } else {
      const dt = delta / (src.fps || 30)
      await src.seek(src.currentTime + dt)
    }
    render()
  }, [render])

  const jumpKeyframe = useCallback((direction) => {
    const src = sourceRef.current
    if (!src) return
    const kfs = keyframesRef.current[activeRef.current]
    if (kfs.length === 0) return
    const t = src.currentTime
    const tol = keyTolerance()
    let target = null
    if (direction > 0) target = kfs.find((k) => k.t > t + tol)
    else {
      for (let i = kfs.length - 1; i >= 0; i--) {
        if (kfs[i].t < t - tol) { target = kfs[i]; break }
      }
    }
    if (target) src.seek(target.t).then(render)
  }, [render, keyTolerance])

  const toggleVisibility = useCallback(() => {
    const src = sourceRef.current
    if (!src) return
    const ch = activeRef.current
    const t = src.currentTime
    const idx = findKeyframeAt(ch, t)
    const box = bboxRef.current[ch]
    if (!box) return
    if (idx >= 0) {
      const k = keyframesRef.current[ch][idx]
      if (kfVisible(k)) k.visible = false
      else delete k.visible
    } else {
      upsertKeyframe(ch, box, { visible: false })
    }
    render()
  }, [findKeyframeAt, upsertKeyframe, render])

  const togglePlay = useCallback(() => {
    const src = sourceRef.current
    if (!src) return
    if (playingRef.current) {
      src.pause()
      playingRef.current = false
      setPlaying(false)
    } else {
      playingRef.current = true
      setPlaying(true)
      if (src.kind === 'video') {
        src.play()
        const loop = () => {
          if (!playingRef.current) return
          render()
          if (src.isPaused) { playingRef.current = false; setPlaying(false); return }
          requestAnimationFrame(loop)
        }
        requestAnimationFrame(loop)
      } else {
        src.play(render)
      }
    }
  }, [render])

  useEffect(() => {
    const onKey = (e) => {
      if (!sourceRef.current) return
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.code === 'Space') { e.preventDefault(); togglePlay() }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); stepFrame(e.shiftKey ? -10 : -1) }
      else if (e.code === 'ArrowRight') { e.preventDefault(); stepFrame(e.shiftKey ? 10 : 1) }
      else if (e.code === 'Tab') { e.preventDefault(); setActiveCh(activeRef.current === 'a' ? 'b' : 'a') }
      else if (e.code === 'KeyK') { e.preventDefault(); upsertKeyframe(activeRef.current, bboxRef.current[activeRef.current]); render() }
      else if (e.code === 'Delete' || e.code === 'Backspace') { e.preventDefault(); removeKeyframeAt(activeRef.current); render() }
      else if (e.code === 'Digit1') { e.preventDefault(); jumpKeyframe(-1) }
      else if (e.code === 'Digit2') { e.preventDefault(); jumpKeyframe(+1) }
      else if (e.code === 'KeyH') { e.preventDefault(); toggleVisibility() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [togglePlay, stepFrame, setActiveCh, upsertKeyframe, removeKeyframeAt, render, jumpKeyframe, toggleVisibility])

  const getCanvasCoords = useCallback((e) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const scaleX = canvasRef.current.width / rect.width
    const scaleY = canvasRef.current.height / rect.height
    return { x: (e.clientX - rect.left) * scaleX, y: (e.clientY - rect.top) * scaleY }
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      if (!draggingRef.current) return
      const p = getCanvasCoords(e)
      const dx = p.x - draggingRef.current.startX
      const dy = p.y - draggingRef.current.startY
      const o = draggingRef.current.orig
      const m = draggingRef.current.mode
      const b = bboxRef.current[draggingRef.current.ch]
      if (m === 'rotate') {
        const ctr = boxCenter(o)
        const ang = Math.atan2(p.y - ctr.y, p.x - ctr.x)
        let deg = (ang * 180) / Math.PI + 90
        while (deg > 180) deg -= 360
        while (deg < -180) deg += 360
        b.angle = deg
        b.x = o.x; b.y = o.y; b.w = o.w; b.h = o.h
        render()
        return
      }
      if (m === 'move') {
        b.x = o.x + dx; b.y = o.y + dy
        b.w = o.w; b.h = o.h; b.angle = o.angle || 0
        render()
        return
      }
      const a = ((o.angle || 0) * Math.PI) / 180
      const cosA = Math.cos(a), sinA = Math.sin(a)
      const localDx = dx * Math.cos(-a) - dy * Math.sin(-a)
      const localDy = dx * Math.sin(-a) + dy * Math.cos(-a)
      const moveE = m.includes('e'), moveW = m.includes('w'), moveS = m.includes('s'), moveN = m.includes('n')
      let newW = o.w + (moveE ? localDx : moveW ? -localDx : 0)
      let newH = o.h + (moveS ? localDy : moveN ? -localDy : 0)
      if (e.shiftKey && ['nw', 'ne', 'sw', 'se'].includes(m)) {
        const aspect = o.w / o.h
        const wDriven = Math.abs(newW / o.w - 1) >= Math.abs(newH / o.h - 1)
        if (wDriven) newH = newW / aspect
        else newW = newH * aspect
      }
      newW = Math.max(4, newW)
      newH = Math.max(4, newH)
      const fixedLocalX = moveE ? -o.w / 2 : moveW ? o.w / 2 : 0
      const fixedLocalY = moveS ? -o.h / 2 : moveN ? o.h / 2 : 0
      const oldCtr = boxCenter(o)
      const fixedWX = oldCtr.x + fixedLocalX * cosA - fixedLocalY * sinA
      const fixedWY = oldCtr.y + fixedLocalX * sinA + fixedLocalY * cosA
      const newFixedLocalX = moveE ? -newW / 2 : moveW ? newW / 2 : 0
      const newFixedLocalY = moveS ? -newH / 2 : moveN ? newH / 2 : 0
      const newCx = fixedWX - (newFixedLocalX * cosA - newFixedLocalY * sinA)
      const newCy = fixedWY - (newFixedLocalX * sinA + newFixedLocalY * cosA)
      b.x = newCx - newW / 2
      b.y = newCy - newH / 2
      b.w = newW
      b.h = newH
      b.angle = o.angle || 0
      render()
    }
    const onUp = () => {
      if (draggingRef.current) {
        upsertKeyframe(draggingRef.current.ch, bboxRef.current[draggingRef.current.ch])
        draggingRef.current = null
        render()
      }
      tlDragRef.current = false
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [getCanvasCoords, render, upsertKeyframe])

  const onCanvasDown = (e) => {
    if (!sourceRef.current) return
    const p = getCanvasCoords(e)
    const order = [activeRef.current, activeRef.current === 'a' ? 'b' : 'a']
    for (const ch of order) {
      const box = bboxRef.current[ch]
      if (!box) continue
      const mode = hitTest(box, p.x, p.y)
      if (mode) {
        if (ch !== activeRef.current) setActiveCh(ch)
        draggingRef.current = { ch, mode, startX: p.x, startY: p.y, orig: { ...box } }
        e.preventDefault()
        render()
        return
      }
    }
  }

  const seekFromTimeline = useCallback(async (e) => {
    const src = sourceRef.current
    const tl = timelineRef.current
    if (!src || !tl) return
    const rect = tl.getBoundingClientRect()
    const r = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    await src.seek(r * src.duration)
    render()
  }, [render])

  useEffect(() => {
    const onMove = (e) => { if (tlDragRef.current) seekFromTimeline(e) }
    window.addEventListener('mousemove', onMove)
    return () => window.removeEventListener('mousemove', onMove)
  }, [seekFromTimeline])

  const loadFromFile = useCallback(async (file, annotations) => {
    setError(null)
    setLoaded(false)
    setLoading(true)
    try {
      if (sourceRef.current && sourceRef.current.dispose) sourceRef.current.dispose()
      const src = await loadSource(file)
      sourceRef.current = src
      keyframesRef.current = {
        a: Array.isArray(annotations?.keyframes?.a) ? annotations.keyframes.a.map((k) => ({ ...k })) : [],
        b: Array.isArray(annotations?.keyframes?.b) ? annotations.keyframes.b.map((k) => ({ ...k })) : [],
      }
      bboxRef.current = { a: null, b: null }
      canvasRef.current.width = src.width
      canvasRef.current.height = src.height
      setFps(src.fps)
      setSourceKind(src.kind)
      setDuration(src.duration)
      await src.seek(0)
      render()
      setLoaded(true)
    } catch (e) {
      setError(e.message || String(e))
      throw e
    } finally {
      setLoading(false)
    }
  }, [render])

  const loadFromUrl = useCallback(async (mediaUrl, filename, annotations, extraHeaders = {}) => {
    const res = await fetch(mediaUrl, { credentials: 'include', headers: extraHeaders })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const blob = await res.blob()
    const extMime = { gif: 'image/gif', webp: 'image/webp', mp4: 'video/mp4', webm: 'video/webm', mov: 'video/quicktime' }
    const ext = (filename.split('.').pop() || '').toLowerCase()
    const type = extMime[ext] || (blob.type && blob.type !== 'application/octet-stream' ? blob.type : 'application/octet-stream')
    const file = new File([blob], filename, { type })
    await loadFromFile(file, annotations)
  }, [loadFromFile])

  const getAnnotations = useCallback(() => {
    const src = sourceRef.current
    if (!src) return null
    const hasA = keyframesRef.current.a.length > 0
    const hasB = keyframesRef.current.b.length > 0
    if (!hasA || !hasB) {
      return { error: 'нужно поставить хотя бы один keyframe для A и для B' }
    }
    return {
      data: {
        source: src.file.name,
        kind: src.kind,
        width: src.width,
        height: src.height,
        fps: src.fps,
        duration: src.duration,
        frames: src.frames,
        keyframes: {
          a: keyframesRef.current.a.map((k) => ({ ...k })),
          b: keyframesRef.current.b.map((k) => ({ ...k })),
        },
      },
      file: src.file,
    }
  }, [])

  useImperativeHandle(ref, () => ({
    loadFromFile,
    loadFromUrl,
    getAnnotations,
    isLoaded: () => loaded,
  }), [loadFromFile, loadFromUrl, getAnnotations, loaded])

  const applySize = (field, value) => {
    const v = parseFloat(value)
    if (!Number.isFinite(v) || v < 2) return
    const ch = activeRef.current
    const b = bboxRef.current[ch]
    if (!b) return
    const cx = b.x + b.w / 2
    const cy = b.y + b.h / 2
    if (field === 'w') { b.w = v; b.x = cx - v / 2 }
    else if (field === 'h') { b.h = v; b.y = cy - v / 2 }
    else if (field === 'angle') b.angle = v
    upsertKeyframe(ch, b)
    render()
  }

  const applySizeToAll = () => {
    const ch = activeRef.current
    const b = bboxRef.current[ch]
    if (!b) return
    keyframesRef.current[ch] = keyframesRef.current[ch].map((k) => {
      const cx = k.x + k.w / 2
      const cy = k.y + k.h / 2
      return { ...k, w: b.w, h: b.h, x: cx - b.w / 2, y: cy - b.h / 2 }
    })
    render()
  }

  const handleFpsChange = (v) => {
    const val = parseFloat(v)
    if (val > 0 && sourceRef.current && sourceRef.current.kind === 'video') {
      sourceRef.current.setFps(val)
      setFps(val)
      render()
    }
  }

  useEffect(() => {
    const el = timelineRef.current
    if (!el) return
    const update = () => setTlWidth(el.offsetWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="flex flex-col gap-2">
      {error && (
        <div className="bg-red-500/15 text-red-300 text-sm rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      <div className="bg-black rounded-xl flex items-center justify-center overflow-hidden" style={{ minHeight: '40vh' }}>
        <canvas
          ref={canvasRef}
          onMouseDown={onCanvasDown}
          className="block max-w-full"
          style={{ maxHeight: '55vh', width: 'auto', height: 'auto', cursor: 'crosshair', userSelect: 'none', display: loaded ? 'block' : 'none' }}
        />
        {!loaded && (
          <div className="text-spotify-text/60 text-sm py-12">
            {error ? 'не удалось загрузить' : loading ? 'загружаю…' : 'выбери файл'}
          </div>
        )}
      </div>

      <div
        ref={timelineRef}
        onMouseDown={(e) => { tlDragRef.current = true; seekFromTimeline(e) }}
        className="relative h-7 bg-spotify-gray rounded cursor-pointer select-none"
      >
        <div className="absolute inset-y-0 left-0 bg-gold/20 pointer-events-none" style={{ width: playheadRatio * tlWidth + 'px' }} />
        <div className="absolute -inset-y-0.5 w-0.5 bg-white pointer-events-none" style={{ left: playheadRatio * tlWidth + 'px' }} />
        {keyframeMarkers.map((kf, i) => (
          <div
            key={`${kf.ch}-${i}`}
            className="absolute top-0.5 bottom-0.5 w-[3px] rounded-sm pointer-events-none"
            style={{
              left: (kf.t / Math.max(duration, 1e-6)) * tlWidth + 'px',
              background: COLORS[kf.ch],
            }}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <button
          onClick={togglePlay}
          disabled={!loaded}
          className="px-3 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
        >{playing ? 'Pause' : 'Play'}</button>
        <button
          onClick={() => stepFrame(-1)}
          disabled={!loaded}
          className="px-2.5 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
        >◀</button>
        <button
          onClick={() => stepFrame(+1)}
          disabled={!loaded}
          className="px-2.5 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
        >▶</button>
        <button
          onClick={() => setActiveCh('a')}
          disabled={!loaded}
          className={`px-3 py-1.5 rounded-md font-semibold disabled:opacity-40 ${active === 'a' ? 'text-white' : 'bg-white/5 text-white hover:bg-white/10'}`}
          style={active === 'a' ? { background: COLORS.a, color: '#fff' } : undefined}
        >A</button>
        <button
          onClick={() => setActiveCh('b')}
          disabled={!loaded}
          className={`px-3 py-1.5 rounded-md font-semibold disabled:opacity-40 ${active === 'b' ? 'text-black' : 'bg-white/5 text-white hover:bg-white/10'}`}
          style={active === 'b' ? { background: COLORS.b, color: '#111' } : undefined}
        >B</button>
        <button
          onClick={() => { upsertKeyframe(activeRef.current, bboxRef.current[activeRef.current]); render() }}
          disabled={!loaded}
          className="px-3 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
        >+ Keyframe</button>
        <button
          onClick={() => { removeKeyframeAt(activeRef.current); render() }}
          disabled={!loaded}
          className="px-3 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
        >− Keyframe</button>

        <label className="flex items-center gap-1 text-spotify-text">
          w
          <input
            type="number"
            min="2"
            step="1"
            value={size.w}
            onChange={(e) => setSize((s) => ({ ...s, w: e.target.value }))}
            onBlur={(e) => applySize('w', e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') applySize('w', e.target.value) }}
            className="w-16 bg-black/40 text-white rounded px-2 py-1 border border-white/10 focus:border-gold focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-1 text-spotify-text">
          h
          <input
            type="number"
            min="2"
            step="1"
            value={size.h}
            onChange={(e) => setSize((s) => ({ ...s, h: e.target.value }))}
            onBlur={(e) => applySize('h', e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') applySize('h', e.target.value) }}
            className="w-16 bg-black/40 text-white rounded px-2 py-1 border border-white/10 focus:border-gold focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-1 text-spotify-text">
          ∠
          <input
            type="number"
            step="1"
            value={size.angle}
            onChange={(e) => setSize((s) => ({ ...s, angle: e.target.value }))}
            onBlur={(e) => applySize('angle', e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') applySize('angle', e.target.value) }}
            className="w-16 bg-black/40 text-white rounded px-2 py-1 border border-white/10 focus:border-gold focus:outline-none"
          />
        </label>
        <button
          onClick={applySizeToAll}
          disabled={!loaded}
          className="px-2.5 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
          title="Apply current W×H to all keyframes of active character"
        >size→all</button>
        <button
          onClick={toggleVisibility}
          disabled={!loaded}
          className="px-2.5 py-1.5 rounded-md bg-white/5 text-white hover:bg-white/10 disabled:opacity-40"
          title="Toggle visibility of keyframe at current time (H)"
        >hide/show</button>
        {sourceKind === 'video' && (
          <label className="flex items-center gap-1 text-spotify-text">
            fps
            <input
              type="number"
              min="1"
              max="120"
              step="0.01"
              value={fps}
              onChange={(e) => setFps(e.target.value)}
              onBlur={(e) => handleFpsChange(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFpsChange(e.target.value) }}
              className="w-20 bg-black/40 text-white rounded px-2 py-1 border border-white/10 focus:border-gold focus:outline-none"
            />
          </label>
        )}
        <span className="text-spotify-text/60 font-mono ml-auto">{info}</span>
      </div>

      <div className="text-spotify-text/50 text-[11px] leading-relaxed">
        <kbd className="px-1 rounded bg-white/5 text-white/80">Space</kbd> play/pause ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">←/→</kbd> ±1 frame ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">⇧←/⇧→</kbd> ±10 ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">Tab</kbd> A/B ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">K</kbd> add ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">⌫</kbd> remove ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">1/2</kbd> prev/next kf ·{' '}
        <kbd className="px-1 rounded bg-white/5 text-white/80">H</kbd> hide · drag rot. handle to rotate · ⇧+corner = proportional
      </div>
    </div>
  )
})

export default Annotator
