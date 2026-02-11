import { useState, useRef, useEffect } from 'react'
import { Download, FileJson, FileSpreadsheet, FileText } from 'lucide-react'
import clsx from 'clsx'
import { ExportFormat } from '@/lib/export'

interface ExportMenuProps {
  onExport: (format: ExportFormat) => void
  disabled?: boolean
  label?: string
}

const exportOptions: Array<{ format: ExportFormat; label: string; icon: typeof FileJson; description: string }> = [
  {
    format: 'json',
    label: 'JSON',
    icon: FileJson,
    description: 'Full trace data with formatting',
  },
  {
    format: 'jsonl',
    label: 'JSONL',
    icon: FileText,
    description: 'One trace per line, ready for ML',
  },
  {
    format: 'csv',
    label: 'CSV',
    icon: FileSpreadsheet,
    description: 'Spans only, for spreadsheets',
  },
]

export default function ExportMenu({ onExport, disabled, label = 'Export' }: ExportMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleExport = (format: ExportFormat) => {
    onExport(format)
    setIsOpen(false)
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={disabled}
        className={clsx(
          'inline-flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
          disabled
            ? 'bg-dark-700 text-muted-400 cursor-not-allowed'
            : 'bg-dark-900 border border-dark-700 text-muted-200 hover:bg-dark-800'
        )}
      >
        <Download className="h-4 w-4" />
        {label}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-1 w-56 bg-dark-900 rounded-lg shadow-lg border border-dark-700 py-1 z-10">
          {exportOptions.map((option) => (
            <button
              key={option.format}
              onClick={() => handleExport(option.format)}
              className="w-full flex items-start gap-3 px-3 py-2 text-left hover:bg-dark-800 transition-colors"
            >
              <option.icon className="h-5 w-5 text-muted-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-muted-100">{option.label}</p>
                <p className="text-xs text-muted-400">{option.description}</p>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
