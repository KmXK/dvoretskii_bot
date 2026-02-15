import { createContext, useContext, useMemo } from 'react'
import WebApp from '@twa-dev/sdk'

const TelegramContext = createContext(null)

export function TelegramProvider({ children }) {
  const value = useMemo(() => {
    const user = WebApp.initDataUnsafe?.user
    return {
      user: user ?? null,
      userId: user?.id ?? null,
      firstName: user?.first_name ?? '',
      lastName: user?.last_name ?? '',
      username: user?.username ?? '',
      photoUrl: user?.photo_url ?? null,
      isPremium: user?.is_premium ?? false,
      initData: WebApp.initData,
      webApp: WebApp,
    }
  }, [])

  return (
    <TelegramContext.Provider value={value}>
      {children}
    </TelegramContext.Provider>
  )
}

export function useTelegram() {
  const ctx = useContext(TelegramContext)
  if (!ctx) throw new Error('useTelegram must be used within TelegramProvider')
  return ctx
}
