import { useState, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
} from '@tanstack/react-table'

const data = [
  { id: 1, name: 'Alex', messages: 1420, rewards: 5, role: 'Admin' },
  { id: 2, name: 'Maria', messages: 980, rewards: 3, role: 'Member' },
  { id: 3, name: 'Ivan', messages: 2100, rewards: 8, role: 'Admin' },
  { id: 4, name: 'Olga', messages: 560, rewards: 2, role: 'Member' },
  { id: 5, name: 'Dmitry', messages: 1800, rewards: 6, role: 'Member' },
  { id: 6, name: 'Anna', messages: 340, rewards: 1, role: 'Member' },
  { id: 7, name: 'Pavel', messages: 3200, rewards: 12, role: 'Admin' },
  { id: 8, name: 'Elena', messages: 750, rewards: 4, role: 'Member' },
]

const columns = [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'messages', header: 'Messages' },
  { accessorKey: 'rewards', header: 'Rewards' },
  {
    accessorKey: 'role',
    header: 'Role',
    cell: ({ getValue }) => {
      const role = getValue()
      return (
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
          role === 'Admin'
            ? 'bg-spotify-green/20 text-spotify-green'
            : 'bg-white/10 text-spotify-text'
        }`}>
          {role}
        </span>
      )
    },
  },
]

export default function TablePage() {
  const [sorting, setSorting] = useState([])
  const [globalFilter, setGlobalFilter] = useState('')

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  })

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="px-4 pt-6"
    >
      <h1 className="text-2xl font-bold text-white mb-6">Users</h1>

      <input
        type="text"
        placeholder="Search..."
        value={globalFilter}
        onChange={e => setGlobalFilter(e.target.value)}
        className="w-full bg-spotify-gray rounded-lg px-4 py-2.5 text-white text-sm
          placeholder-spotify-text outline-none focus:ring-2 focus:ring-spotify-green/50 mb-4"
      />

      <div className="bg-spotify-dark rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map(headerGroup => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map(header => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="text-left text-xs font-medium text-spotify-text uppercase tracking-wider
                      px-4 py-3 cursor-pointer hover:text-white transition-colors select-none"
                  >
                    <div className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {{ asc: ' ↑', desc: ' ↓' }[header.column.getIsSorted()] ?? ''}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, i) => (
              <motion.tr
                key={row.id}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: i * 0.03 }}
                className="border-t border-white/5 hover:bg-white/5 transition-colors"
              >
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-4 py-3 text-sm text-white">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </motion.tr>
            ))}
          </tbody>
        </table>

        {table.getRowModel().rows.length === 0 && (
          <div className="text-center py-8 text-spotify-text text-sm">Nothing found</div>
        )}
      </div>
    </motion.div>
  )
}
