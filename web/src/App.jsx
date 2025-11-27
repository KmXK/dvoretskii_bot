import { useEffect, useState } from 'react'
import { init } from '@twa-dev/sdk'
import './App.css'

function App() {
  const [count, setCount] = useState(0)
  const [webApp, setWebApp] = useState(null)

  useEffect(() => {
    // Инициализируем Telegram Web App
    init()
    setWebApp(window.Telegram?.WebApp || null)
    
    if (window.Telegram?.WebApp) {
      // Расширяем приложение на весь экран
      window.Telegram.WebApp.expand()
      // Показываем главную кнопку (опционально)
      // window.Telegram.WebApp.MainButton.show()
    }
  }, [])

  const handleClose = () => {
    if (webApp) {
      webApp.close()
    }
  }

  return (
    <>
      <div>
        <h1>Telegram Mini App</h1>
        {webApp && (
          <div>
            <p>Привет, {webApp.initDataUnsafe?.user?.first_name || 'пользователь'}!</p>
            <p>Версия: {webApp.version}</p>
            <p>Платформа: {webApp.platform}</p>
          </div>
        )}
      </div>
      <div className="card">
        <button onClick={() => setCount((count) => count + 1)}>
          count is {count}
        </button>
        <p>
          Edit <code>src/App.jsx</code> and save to test HMR
        </p>
      </div>
      {webApp && (
        <button onClick={handleClose} style={{ marginTop: '20px' }}>
          Закрыть приложение
        </button>
      )}
    </>
  )
}

export default App
