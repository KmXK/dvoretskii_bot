import { AnimatePresence } from 'framer-motion'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import ArmyPage from './pages/ArmyPage'
import CasinoPage from './pages/CasinoPage'
import ChartsPage from './pages/ChartsPage'
import FeaturesPage from './pages/FeaturesPage'
import HomePage from './pages/HomePage'
import TablePage from './pages/TablePage'
import TodoPage from './pages/TodoPage'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen pb-16 bg-spotify-black">
        <AnimatePresence mode="wait">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/charts" element={<ChartsPage />} />
            <Route path="/table" element={<TablePage />} />
            <Route path="/casino" element={<CasinoPage />} />
            <Route path="/features" element={<FeaturesPage />} />
            <Route path="/army" element={<ArmyPage />} />
            <Route path="/todo" element={<TodoPage />} />
          </Routes>
        </AnimatePresence>
        <NavBar />
      </div>
    </BrowserRouter>
  )
}
