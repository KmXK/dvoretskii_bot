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
    ],
  },
  {
    label: 'Списки',
    items: [
      { to: '/bills', label: 'Счета', icon: '💸' },
      { to: '/todo', label: 'Задачи', icon: '📝' },
      { to: '/reminders', label: 'Напоминания', icon: '🔔' },
      { to: '/birthdays', label: 'Дни рождения', icon: '🎂' },
      { to: '/army', label: 'Армейка', icon: '🎖️' },
      { to: '/features', label: 'Фичи', icon: '💡' },
    ],
  },
  {
    label: '/fuck',
    items: [
      { to: '/fuck/admin', label: 'Ассеты', icon: '🤡' },
      { to: '/fuck/new', label: 'Создать', icon: '➕' },
    ],
  },
  {
    label: 'Прочее',
    items: [
      { to: '/stats', label: 'Статистика', icon: '📊' },
      { to: '/tools', label: 'Инструменты', icon: '🧰' },
    ],
  },
]

export const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items)
