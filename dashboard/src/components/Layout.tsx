import { Outlet, Link, useLocation } from 'react-router-dom'
import { Activity, LayoutGrid, GitCompare, DollarSign, Tag } from 'lucide-react'
import clsx from 'clsx'

const navigation = [
  { name: 'Traces', href: '/traces', icon: Activity },
  { name: 'Compare', href: '/compare', icon: GitCompare },
  { name: 'Costs', href: '/costs', icon: DollarSign },
  { name: 'Curation', href: '/curation', icon: Tag },
]

export default function Layout() {
  const location = useLocation()

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="bg-white border-b border-slate-200">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center">
              <Link to="/" className="flex items-center gap-2">
                <LayoutGrid className="h-8 w-8 text-primary-600" />
                <span className="text-xl font-semibold text-slate-900">vizpath</span>
              </Link>
              <div className="ml-10 flex items-center space-x-4">
                {navigation.map((item) => {
                  const isActive = location.pathname.startsWith(item.href)
                  return (
                    <Link
                      key={item.name}
                      to={item.href}
                      className={clsx(
                        'flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-md',
                        isActive
                          ? 'bg-primary-50 text-primary-700'
                          : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                      )}
                    >
                      <item.icon className="h-4 w-4" />
                      {item.name}
                    </Link>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </nav>

      <main className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
        <Outlet />
      </main>
    </div>
  )
}
