import { AnimatePresence } from 'framer-motion'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { TelegramProvider } from './context/TelegramContext'
import NavBar from './components/NavBar'
import ArmyPage from './pages/ArmyPage'
import BirthdaysPage from './pages/BirthdaysPage'
import CasinoPage from './pages/CasinoPage'
import PokerPage from './pages/PokerPage'
import BlackjackPage from './pages/BlackjackPage'
import FeaturesPage from './pages/FeaturesPage'
import HomePage from './pages/HomePage'
import ProfilePage from './pages/ProfilePage'
import RemindersPage from './pages/RemindersPage'
import StatsPage from './pages/StatsPage'
import ToolsPage from './pages/ToolsPage'
import NotFoundPage from './pages/NotFoundPage'
import TodoPage from './pages/TodoPage'

export default function App() {
  return (
    <TelegramProvider>
      <BrowserRouter>
        <div className="min-h-screen pb-16 bg-spotify-black">
          <AnimatePresence mode="wait">
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/poker" element={<PokerPage />} />
              <Route path="/blackjack" element={<BlackjackPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/casino" element={<CasinoPage />} />
              <Route path="/features" element={<FeaturesPage />} />
              <Route path="/army" element={<ArmyPage />} />
              <Route path="/todo" element={<TodoPage />} />
              <Route path="/tools" element={<ToolsPage />} />
              <Route path="/reminders" element={<RemindersPage />} />
              <Route path="/birthdays" element={<BirthdaysPage />} />
              <Route path="/stats" element={<StatsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </AnimatePresence>
          <NavBar />
        </div>
      </BrowserRouter>
    </TelegramProvider>
  )
}
