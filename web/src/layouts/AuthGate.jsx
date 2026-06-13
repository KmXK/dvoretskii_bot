import { useAuth } from '../context/useAuth'
import LoginScreen from '../components/LoginScreen'
import MascotLoader from '../components/MascotLoader'

export default function AuthGate({ children }) {
  const { isAuthenticated, loading, loginWithWidget, loginWithOidc } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-spotify-black">
        <MascotLoader label="Дворецкий проверяет, кто пришёл…" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <LoginScreen onLoginWidget={loginWithWidget} onLoginOidc={loginWithOidc} />
  }

  return children
}
