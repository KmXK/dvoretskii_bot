export const NAV_GROUPS = [
  {
    label: 'Главная',
    items: [
      { to: '/', label: 'Главная', icon: '🏠' },
      { to: '/profile', label: 'Профиль', icon: '👤' },
    ],
  },
  {
    label: 'Игры',
    items: [
      { to: '/casino', label: 'Казино', icon: '🎰' },
      { to: '/poker', label: 'Покер', icon: '🃏' },
      { to: '/blackjack', label: 'Блэкджек', icon: '♠️' },
      { to: '/boardgames', label: 'Настолки', icon: '♟️' },
      { to: '/tennis', label: 'Теннис', icon: '🏓', home: { desc: 'Live-табло настольного тенниса', color: 'from-amber-500/20 to-amber-900/20' } },
    ],
  },
  {
    label: 'Списки',
    items: [
      { to: '/bills', label: 'Счета', icon: '💸', home: { desc: 'Совместные расходы', color: 'from-green-500/20 to-green-900/20' } },
      { to: '/todo', label: 'Задачи', icon: '📝', home: { desc: 'Список задач', color: 'from-rose-500/20 to-rose-900/20' } },
      { to: '/reminders', label: 'Напоминания', icon: '🔔', home: { desc: 'Напоминания', color: 'from-blue-500/20 to-blue-900/20' } },
      { to: '/birthdays', label: 'Дни рождения', icon: '🎂', home: { desc: 'Дни рождения', color: 'from-pink-500/20 to-pink-900/20' } },
      { to: '/army', label: 'Армейка', icon: '🎖️', home: { desc: 'Статус по армейке', color: 'from-emerald-500/20 to-emerald-900/20' } },
      { to: '/features', label: 'Фичи', icon: '💡', home: { desc: 'Фича-реквесты', color: 'from-cyan-500/20 to-cyan-900/20' } },
    ],
  },
  {
    label: '/fuck',
    items: [
      { to: '/fuck/assets', label: 'Ассеты', icon: '🤡', home: { title: '/fuck', desc: 'Гифки доступные тебе', color: 'from-fuchsia-500/20 to-fuchsia-900/20' } },
      { to: '/fuck/new', label: 'Создать', icon: '➕' },
    ],
  },
  {
    label: 'Прочее',
    items: [
      { to: '/stats', label: 'Статистика', icon: '📊', home: { desc: 'Статистика чатов', color: 'from-violet-500/20 to-violet-900/20' } },
      { to: '/tools', label: 'Инструменты', icon: '🧰', home: { desc: 'Валюты, перевод, время', color: 'from-amber-500/20 to-amber-900/20' } },
    ],
  },
]

export const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items)

export const HOME_CARDS = ALL_NAV_ITEMS
  .filter((item) => item.home)
  .map((item) => ({
    title: item.home.title ?? item.label,
    desc: item.home.desc,
    emoji: item.icon,
    color: item.home.color,
    to: item.to,
  }))
