import { parseGIF, decompressFrames } from 'gifuct-js'

export class VideoSource {
  constructor(file) { this.file = file; this.kind = 'video' }
  async load() {
    this.url = URL.createObjectURL(this.file)
    this.video = document.createElement('video')
    this.video.src = this.url
    this.video.muted = true
    this.video.playsInline = true
    await new Promise((res, rej) => {
      this.video.onloadedmetadata = res
      this.video.onerror = () => rej(new Error('Failed to load video'))
    })
    this.width = this.video.videoWidth
    this.height = this.video.videoHeight
    this.duration = this.video.duration
    this.fps = 30
    this.frames = Math.round(this.duration * this.fps)
  }
  setFps(fps) { this.fps = fps; this.frames = Math.round(this.duration * fps) }
  async seek(t) {
    t = Math.max(0, Math.min(this.duration - 1e-6, t))
    if (Math.abs(this.video.currentTime - t) < 1e-4) return
    return new Promise((res) => {
      const onSeeked = () => { this.video.removeEventListener('seeked', onSeeked); res() }
      this.video.addEventListener('seeked', onSeeked)
      this.video.currentTime = t
    })
  }
  draw(ctx) { ctx.drawImage(this.video, 0, 0, this.width, this.height) }
  play() { return this.video.play() }
  pause() { this.video.pause() }
  dispose() { if (this.url) URL.revokeObjectURL(this.url) }
  get currentTime() { return this.video.currentTime }
  get isPaused() { return this.video.paused }
}

class FrameArraySource {
  constructor(file, kind) { this.file = file; this.kind = kind; this._t = 0; this._playing = false }
  setFps() {}
  _finalize() {
    const fd = this.frameData
    this.duration = fd.length ? fd[fd.length - 1].t + fd[fd.length - 1].delay : 0
    this.frames = fd.length
    this.fps = this.duration > 0 ? this.frames / this.duration : 0
  }
  _frameIdxAt(t) {
    const fd = this.frameData
    if (!fd.length) return 0
    if (t <= 0) return 0
    if (t >= this.duration) return fd.length - 1
    let lo = 0, hi = fd.length - 1
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1
      if (fd[mid].t <= t) lo = mid; else hi = mid - 1
    }
    return lo
  }
  async seek(t) { this._t = Math.max(0, Math.min(this.duration, t)) }
  draw(ctx) {
    const f = this.frameData[this._frameIdxAt(this._t)]
    if (f) ctx.drawImage(f.bitmap, 0, 0)
  }
  play(onFrame) {
    if (this._playing || this.duration <= 0) return
    this._playing = true
    const startPerf = performance.now() - this._t * 1000
    const tick = () => {
      if (!this._playing) return
      const elapsed = (performance.now() - startPerf) / 1000
      this._t = elapsed % this.duration
      onFrame && onFrame()
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  }
  pause() { this._playing = false }
  dispose() {}
  get currentTime() { return this._t }
  get isPaused() { return !this._playing }
}

export class GifSource extends FrameArraySource {
  constructor(file) { super(file, 'gif') }
  async load() {
    const buf = await this.file.arrayBuffer()
    const gif = parseGIF(buf)
    const decompressed = decompressFrames(gif, true)
    if (decompressed.length === 0) throw new Error('GIF has no frames')
    this.width = gif.lsd.width
    this.height = gif.lsd.height

    const off = document.createElement('canvas')
    off.width = this.width; off.height = this.height
    const offCtx = off.getContext('2d')

    const patchCanvas = document.createElement('canvas')
    const patchCtx = patchCanvas.getContext('2d')

    this.frameData = []
    let cumMs = 0
    for (const f of decompressed) {
      const before = offCtx.getImageData(0, 0, this.width, this.height)
      patchCanvas.width = f.dims.width
      patchCanvas.height = f.dims.height
      const pd = patchCtx.createImageData(f.dims.width, f.dims.height)
      pd.data.set(f.patch)
      patchCtx.putImageData(pd, 0, 0)
      offCtx.drawImage(patchCanvas, f.dims.left, f.dims.top)

      const bitmap = await createImageBitmap(off)
      const delayMs = f.delay || 100
      this.frameData.push({ bitmap, t: cumMs / 1000, delay: delayMs / 1000 })
      cumMs += delayMs

      if (f.disposalType === 2) offCtx.clearRect(f.dims.left, f.dims.top, f.dims.width, f.dims.height)
      else if (f.disposalType === 3) offCtx.putImageData(before, 0, 0)
    }
    this._finalize()
  }
}

export class WebpSource extends FrameArraySource {
  constructor(file) { super(file, 'webp') }
  async load() {
    const mime = this.file.type || 'image/webp'
    if (typeof ImageDecoder !== 'undefined' && (await ImageDecoder.isTypeSupported(mime))) {
      try {
        await this._loadAnimated(mime)
        return
      } catch (err) {
        console.warn('animated webp decode failed, falling back to static:', err)
      }
    }
    await this._loadStatic()
  }
  async _loadAnimated(mime) {
    const decoder = new ImageDecoder({ data: this.file.stream(), type: mime })
    await decoder.completed
    const track = decoder.tracks.selectedTrack
    const frameCount = track ? track.frameCount : 1
    if (!frameCount) throw new Error('WebP has no frames')
    this.frameData = []
    let cumUs = 0
    for (let i = 0; i < frameCount; i++) {
      const result = await decoder.decode({ frameIndex: i })
      const vf = result.image
      if (i === 0) { this.width = vf.displayWidth; this.height = vf.displayHeight }
      const durationUs = vf.duration || 100000
      const bitmap = await createImageBitmap(vf)
      vf.close()
      this.frameData.push({ bitmap, t: cumUs / 1e6, delay: durationUs / 1e6 })
      cumUs += durationUs
    }
    decoder.close()
    this._finalize()
    if (this.duration === 0) {
      this.duration = 1
      this.frameData[0].delay = 1
      this._finalize()
    }
  }
  async _loadStatic() {
    const url = URL.createObjectURL(this.file)
    try {
      const img = await new Promise((res, rej) => {
        const el = new Image()
        el.onload = () => res(el)
        el.onerror = () => rej(new Error('failed to load webp as static image'))
        el.src = url
      })
      this.width = img.naturalWidth
      this.height = img.naturalHeight
      const bitmap = await createImageBitmap(img)
      this.frameData = [{ bitmap, t: 0, delay: 1 }]
      this._finalize()
      if (!this.duration) {
        this.duration = 1
        this.fps = 1
      }
    } finally {
      URL.revokeObjectURL(url)
    }
  }
}

export async function loadSource(file) {
  const isGif = file.type === 'image/gif' || /\.gif$/i.test(file.name)
  const isWebp = file.type === 'image/webp' || /\.webp$/i.test(file.name)
  let src
  if (isGif) src = new GifSource(file)
  else if (isWebp) src = new WebpSource(file)
  else src = new VideoSource(file)
  try {
    await src.load()
  } catch (err) {
    src.dispose && src.dispose()
    throw err
  }
  if (!Number.isFinite(src.width) || !Number.isFinite(src.height) || !Number.isFinite(src.duration)) {
    throw new Error(`не удалось декодировать ${src.kind} (${file.type || 'unknown mime'}, ${file.size} bytes)`)
  }
  if (!Number.isFinite(src.fps)) src.fps = 30
  if (!Number.isFinite(src.frames)) src.frames = Math.max(1, Math.round(src.duration * src.fps))
  return src
}
