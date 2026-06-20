import { Outlet, Link, useLocation } from 'react-router-dom'
import {
  Activity,
  LayoutGrid,
  GitCompare,
  DollarSign,
  Tag,
  Rocket,
  FlaskConical,
  Brain,
  AlertTriangle,
  BellRing,
  Database,
  Gauge,
} from 'lucide-react'
import clsx from 'clsx'

const primaryNavigation = [
  { name: 'Traces', href: '/traces', icon: Activity },
  { name: 'Failures', href: '/inbox', icon: AlertTriangle },
  { name: 'Experiments', href: '/experiments', icon: FlaskConical },
  { name: 'Compare', href: '/compare', icon: GitCompare },
  { name: 'Intelligence', href: '/intelligence', icon: Brain },
  { name: 'Operations', href: '/operations', icon: Gauge },
  { name: 'Alerts', href: '/alerts', icon: BellRing },
  { name: 'Datasets', href: '/datasets', icon: Database },
  { name: 'Costs', href: '/costs', icon: DollarSign },
  { name: 'Curation', href: '/curation', icon: Tag },
]

const secondaryNavigation = [
  { name: 'Demo', href: '/demo', icon: Rocket },
]

const navigationGroups = [primaryNavigation, secondaryNavigation]

export default function Layout() {
  const location = useLocation()

  return (
    <div className="min-h-screen bg-dark-900 flex">
      {/* Dark sidebar */}
      <nav className="w-56 bg-dark-950 border-r border-dark-700 flex flex-col">
        <div className="p-4">
          <Link to="/" className="flex items-center gap-2">
            <LayoutGrid className="h-7 w-7 text-nvidia" />
            <span className="text-lg font-bold text-muted-100 font-mono tracking-tight">
              vizpath
            </span>
          </Link>
        </div>

        <div className="flex-1 px-2 py-4 space-y-4">
          {navigationGroups.map((group, groupIndex) => (
            <div
              key={groupIndex}
              className={clsx(groupIndex > 0 && 'border-t border-dark-800 pt-4')}
            >
              <div className="space-y-1">
                {group.map((item) => {
                  const isActive =
                    location.pathname === item.href ||
                    location.pathname.startsWith(item.href + '/')
                  return (
                    <Link
                      key={item.name}
                      to={item.href}
                      className={clsx(
                        'flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors relative',
                        isActive
                          ? 'bg-dark-800 text-nvidia'
                          : 'text-muted-300 hover:bg-dark-800 hover:text-muted-100'
                      )}
                    >
                      {isActive && (
                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-nvidia rounded-r" />
                      )}
                      <item.icon className="h-4 w-4" />
                      {item.name}
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="p-4 border-t border-dark-700">
          <p className="text-xs text-muted-400 font-mono">Nemotron-powered</p>
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <div className="mx-auto max-w-7xl px-6 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
