import { motion } from 'framer-motion'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, PieChart, Pie, Cell,
} from 'recharts'

const barData = [
  { name: 'Пн', messages: 124 },
  { name: 'Вт', messages: 210 },
  { name: 'Ср', messages: 165 },
  { name: 'Чт', messages: 290 },
  { name: 'Пт', messages: 340 },
  { name: 'Сб', messages: 180 },
  { name: 'Вс', messages: 95 },
]

const lineData = [
  { day: '1', users: 12 },
  { day: '5', users: 18 },
  { day: '10', users: 15 },
  { day: '15', users: 25 },
  { day: '20', users: 22 },
  { day: '25', users: 30 },
  { day: '30', users: 28 },
]

const pieData = [
  { name: 'Text', value: 65 },
  { name: 'Photo', value: 20 },
  { name: 'Voice', value: 10 },
  { name: 'Video', value: 5 },
]

const PIE_COLORS = ['#1DB954', '#1ed760', '#169c46', '#b3b3b3']

const chartTooltipStyle = {
  contentStyle: {
    background: '#282828',
    border: 'none',
    borderRadius: '8px',
    color: '#fff',
    fontSize: '12px',
  },
}

export default function ChartsPage() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6"
    >
      <h1 className="text-2xl font-bold text-white mb-6">Charts</h1>

      <div className="bg-spotify-dark rounded-xl p-4 mb-4">
        <h2 className="text-white font-semibold text-sm mb-4">Messages per day</h2>
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={barData}>
            <XAxis dataKey="name" tick={{ fill: '#B3B3B3', fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#B3B3B3', fontSize: 12 }} axisLine={false} tickLine={false} width={30} />
            <Tooltip {...chartTooltipStyle} />
            <Bar dataKey="messages" fill="#1DB954" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-spotify-dark rounded-xl p-4 mb-4">
        <h2 className="text-white font-semibold text-sm mb-4">Active users (month)</h2>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={lineData}>
            <XAxis dataKey="day" tick={{ fill: '#B3B3B3', fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#B3B3B3', fontSize: 12 }} axisLine={false} tickLine={false} width={30} />
            <Tooltip {...chartTooltipStyle} />
            <Line type="monotone" dataKey="users" stroke="#1DB954" strokeWidth={2} dot={{ fill: '#1DB954', r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="bg-spotify-dark rounded-xl p-4">
        <h2 className="text-white font-semibold text-sm mb-4">Message types</h2>
        <div className="flex items-center gap-4">
          <ResponsiveContainer width="50%" height={160}>
            <PieChart>
              <Pie data={pieData} cx="50%" cy="50%" innerRadius={40} outerRadius={65} dataKey="value" stroke="none">
                {pieData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i]} />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="flex flex-col gap-2">
            {pieData.map((entry, i) => (
              <div key={entry.name} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full" style={{ background: PIE_COLORS[i] }} />
                <span className="text-spotify-text text-xs">{entry.name} — {entry.value}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  )
}
