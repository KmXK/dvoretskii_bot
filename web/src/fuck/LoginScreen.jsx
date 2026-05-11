import { useEffect, useRef, useState } from 'react'
import { api } from './api'

export default function LoginScreen({ onLogin }) {
  const containerRef = useRef(null)
  const [botUsername, setBotUsername] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.config()
      .then((cfg) => setBotUsername(cfg.bot_username))
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!botUsername || !containerRef.current) return

    window.onTelegramAuth = (user) => onLogin(user)

    const script = document.createElement('script')
    script.async = true
    script.src = 'https://telegram.org/js/telegram-widget.js?22'
    script.setAttribute('data-telegram-login', botUsername)
    script.setAttribute('data-size', 'large')
    script.setAttribute('data-radius', '8')
    script.setAttribute('data-onauth', 'onTelegramAuth(user)')
    script.setAttribute('data-request-access', 'write')

    containerRef.current.innerHTML = ''
    containerRef.current.appendChild(script)
  }, [botUsername, onLogin])

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-spotify-black text-white">
      <div className="max-w-md w-full text-center">
        <div className="text-6xl mb-6">🤡</div>
        <h1 className="text-3xl font-bold mb-3">/fuck</h1>
        <p className="text-spotify-text text-base mb-10">
          Войди через Telegram чтобы посмотреть и управлять своими гифками.
        </p>

        {error && (
          <div className="bg-red-500/15 text-red-300 text-sm rounded-xl px-4 py-3 mb-6">
            {error}
          </div>
        )}
        {!botUsername && !error && (
          <p className="text-spotify-text text-sm mb-6">Загружаю конфигурацию…</p>
        )}

        <div ref={containerRef} className="flex justify-center" />

        <p className="text-xs text-spotify-text/50 mt-10 leading-relaxed">
          Если открыто из бота через мини-приложение — авторизация произойдёт автоматически.
        </p>
      </div>
    </div>
  )
}
