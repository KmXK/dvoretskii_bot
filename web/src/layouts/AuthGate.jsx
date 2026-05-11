import { useAuth } from '../context/useAuth'
import LoginScreen from '../components/LoginScreen'

export default function AuthGate({ children }) {
  const { isAuthenticated, loading, loginWithWidget } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-spotify-black">
        <div className="w-8 h-8 border-2 border-spotify-green border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (!isAuthenticated) return <LoginScreen onLogin={loginWithWidget} />

  return children
}
