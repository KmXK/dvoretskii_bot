import {
  Home, User, Dices, Spade, Club, Castle, Trophy, Receipt, ListChecks,
  TriangleAlert, Bell, Cake, Medal, Lightbulb, Sticker, Plus, ChartColumn,
  Wrench, Settings,
} from 'lucide-react'

export const NAV_GROUPS = [
  {
    label: 'Главная',
    items: [
      { to: '/', label: 'Главная', Icon: Home },
      { to: '/profile', label: 'Профиль', Icon: User },
    ],
  },
  {
    label: 'Игры',
    items: [
      { to: '/casino', label: 'Казино', Icon: Dices, home: { desc: 'Слоты и рулетка', tint: 'gold' } },
      { to: '/poker', label: 'Покер', Icon: Spade, home: { desc: 'Столы онлайн', tint: 'indigo' } },
      { to: '/blackjack', label: 'Блэкджек', Icon: Club, home: { desc: '21 очко', tint: 'rose' } },
      { to: '/boardgames', label: 'Настолки', Icon: Castle, home: { desc: 'Шахматы, шашки', tint: 'green' } },
      { to: '/tennis', label: 'Теннис', Icon: Trophy, home: { desc: 'Live-табло тенниса и сквоша', tint: 'gold' } },
    ],
  },
  {
    label: 'Списки',
    items: [
      { to: '/bills', label: 'Счета', Icon: Receipt, home: { desc: 'Совместные расходы', tint: 'green' } },
      { to: '/todo', label: 'Задачи', Icon: ListChecks, home: { desc: 'Список задач', tint: 'rose' } },
      { to: '/incidents', label: 'Инциденты', Icon: TriangleAlert, home: { desc: 'Текущие и закрытые', tint: 'rose' } },
      { to: '/reminders', label: 'Напоминания', Icon: Bell, home: { desc: 'Напоминания', tint: 'indigo' } },
      { to: '/birthdays', label: 'Дни рождения', Icon: Cake, home: { desc: 'Дни рождения', tint: 'gold' } },
      { to: '/army', label: 'Армейка', Icon: Medal, home: { desc: 'Статус по армейке', tint: 'green' } },
      { to: '/features', label: 'Фичи', Icon: Lightbulb, home: { desc: 'Фича-реквесты', tint: 'indigo' } },
    ],
  },
  {
    label: '/fuck',
    items: [
      { to: '/fuck/assets', label: 'Ассеты', Icon: Sticker, home: { title: '/fuck', desc: 'Гифки доступные тебе', tint: 'gold' } },
      { to: '/fuck/new', label: 'Создать', Icon: Plus },
    ],
  },
  {
    label: 'Прочее',
    items: [
      { to: '/stats', label: 'Статистика', Icon: ChartColumn, home: { desc: 'Статистика чатов', tint: 'indigo' } },
      { to: '/tools', label: 'Инструменты', Icon: Wrench, home: { desc: 'Валюты, перевод, время', tint: 'gold' } },
      { to: '/settings', label: 'Настройки', Icon: Settings, home: { desc: 'Функции и роли', tint: 'slate' } },
    ],
  },
]

export const ALL_NAV_ITEMS = NAV_GROUPS.flatMap((g) => g.items)

export const HOME_CARDS = ALL_NAV_ITEMS
  .filter((item) => item.home)
  .map((item) => ({
    title: item.home.title ?? item.label,
    desc: item.home.desc,
    Icon: item.Icon,
    tint: item.home.tint,
    to: item.to,
  }))
