import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

const FEATURES = [
  { icon: '🎰', label: 'Казино и игры' },
  { icon: '💸', label: 'Совместные счета' },
  { icon: '🔔', label: 'Напоминания' },
  { icon: '📊', label: 'Статистика чатов' },
]

export default function LoginScreen({ onLoginWidget, onLoginOidc }) {
  const containerRef = useRef(null)
  const [config, setConfig] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('/api/auth/config')
      .then((cfg) => setConfig(cfg))
      .catch((e) => setError(e.message))
  }, [])

  const useOidc = !!config?.client_id
  const botUsername = config?.bot_username

  useEffect(() => {
    if (!config || !containerRef.current) return

    containerRef.current.innerHTML = ''

    if (useOidc) {
      const initLib = () => {
        if (!window.Telegram?.Login) return
        window.Telegram.Login.init({
          client_id: config.client_id,
          request_access: 'write',
        }, (result) => {
          if (result?.id_token) {
            onLoginOidc(result.id_token).catch((e) => setError(e.message))
          } else if (result?.error && result.error !== 'popup_closed') {
            setError(result.error)
          }
        })
      }
      if (window.Telegram?.Login) {
        initLib()
      } else {
        let script = document.getElementById('tg-login-lib')
        if (!script) {
          script = document.createElement('script')
          script.id = 'tg-login-lib'
          script.async = true
          script.src = 'https://telegram.org/js/telegram-login.js'
          document.body.appendChild(script)
        }
        script.addEventListener('load', initLib, { once: true })
      }

      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'tg-auth-button'
      btn.textContent = 'Войти через Telegram'
      containerRef.current.appendChild(btn)
      return
    }

    if (!botUsername) return
    window.onTelegramAuth = (user) => onLoginWidget(user)
    const script = document.createElement('script')
    script.async = true
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.setAttribute('data-telegram-login', botUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-radius', '8')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    script.setAttribute('data-request-access', 'write')
    containerRef.current.appendChild(script)
  }, [config, useOidc, botUsername, onLoginWidget, onLoginOidc])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-spotify-black text-white relative overflow-hidden">
      <div className="absolute inset-0 -z-10 opacity-40">
        <div className="absolute top-1/4 left-1/4 w-72 h-72 rounded-full bg-spotify-green/20 blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-72 h-72 rounded-full bg-emerald-500/10 blur-3xl" />
      </div>

      <div className="max-w-md w-full text-center">
        <div className="inline-flex items-center justify-center w-20 h-20 rounded-2xl bg-gradient-to-br from-spotify-green to-emerald-700 text-5xl mb-6 shadow-xl">
          🤖
        </div>
        <h1 className="text-4xl font-bold mb-3 tracking-tight">Dvoretskiy</h1>
        <p className="text-spotify-text text-base mb-2">
          Внутренний бот и веб-приложение для своих.
        </p>
        <p className="text-spotify-text/70 text-sm mb-8">
          Войди через Telegram, чтобы получить доступ ко всем разделам.
        </p>

        <div className="grid grid-cols-2 gap-2 mb-8">
          {FEATURES.map((f) => (
            <div
              key={f.label}
              className="bg-white/5 border border-white/5 rounded-xl px-3 py-2.5 flex items-center gap-2 text-left"
            >
              <span className="text-lg">{f.icon}</span>
              <span className="text-spotify-text text-xs">{f.label}</span>
            </div>
          ))}
        </div>

        {error && (
          <div className="bg-red-500/15 text-red-300 text-sm rounded-xl px-4 py-3 mb-6">
            {error}
          </div>
        )}
        {!config && !error && (
          <p className="text-spotify-text text-sm mb-6">Загружаю конфигурацию…</p>
        )}

        <div ref={containerRef} className="flex justify-center" />

        <p className="text-xs text-spotify-text/50 mt-10 leading-relaxed">
          Если ты открыл это из бота — авторизация произойдёт автоматически.
        </p>
      </div>
    </div>
  )
}
