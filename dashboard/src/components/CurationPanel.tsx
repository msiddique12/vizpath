import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Tag, Star, MessageSquare, Loader2, Check, Trash2 } from 'lucide-react'
import clsx from 'clsx'
import { getLabel, createOrUpdateLabel, deleteLabel } from '@/lib/api'

interface CurationPanelProps {
  traceId: string
  traceName?: string
}

const LABELS = [
  { value: 'excellent', color: 'bg-green-100 text-green-700 border-green-200' },
  { value: 'good', color: 'bg-blue-100 text-blue-700 border-blue-200' },
  { value: 'needs_improvement', color: 'bg-amber-100 text-amber-700 border-amber-200' },
  { value: 'failure', color: 'bg-red-100 text-red-700 border-red-200' },
  { value: 'interesting', color: 'bg-purple-100 text-purple-700 border-purple-200' },
]

export default function CurationPanel({ traceId, traceName: _traceName }: CurationPanelProps) {
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [score, setScore] = useState<number | null>(null)
  const [selectedLabel, setSelectedLabel] = useState<string | null>(null)
  const [hasChanges, setHasChanges] = useState(false)

  const { data: label, isLoading } = useQuery({
    queryKey: ['curation-label', traceId],
    queryFn: () => getLabel(traceId),
  })

  useEffect(() => {
    if (label) {
      setSelectedLabel(label.label)
      setScore(label.quality_score)
      setNotes(label.notes || '')
    }
  }, [label])

  const saveMutation = useMutation({
    mutationFn: () =>
      createOrUpdateLabel({
        trace_id: traceId,
        label: selectedLabel || undefined,
        quality_score: score || undefined,
        notes: notes || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['curation-label', traceId] })
      setHasChanges(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteLabel(traceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['curation-label', traceId] })
      setSelectedLabel(null)
      setScore(null)
      setNotes('')
      setHasChanges(false)
    },
  })

  const handleLabelClick = (value: string) => {
    setSelectedLabel(selectedLabel === value ? null : value)
    setHasChanges(true)
  }

  const handleScoreChange = (newScore: number) => {
    setScore(score === newScore ? null : newScore)
    setHasChanges(true)
  }

  const handleNotesChange = (value: string) => {
    setNotes(value)
    setHasChanges(true)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-5 w-5 text-slate-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="bg-slate-50 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-700 flex items-center gap-2">
          <Tag className="h-4 w-4" />
          Curation
        </h3>
        {label && (
          <span className="text-xs text-slate-500">
            {label.exported ? 'Exported' : 'Not exported'}
          </span>
        )}
      </div>

      <div>
        <p className="text-xs text-slate-500 mb-2">Label</p>
        <div className="flex flex-wrap gap-2">
          {LABELS.map(({ value, color }) => (
            <button
              key={value}
              onClick={() => handleLabelClick(value)}
              className={clsx(
                'px-2.5 py-1 text-xs font-medium rounded-full border transition-all',
                selectedLabel === value
                  ? `${color} ring-2 ring-offset-1 ring-primary-400`
                  : 'bg-white text-slate-600 border-slate-200 hover:border-slate-300'
              )}
            >
              {value.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
          <Star className="h-3 w-3" />
          Quality Score
        </p>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((s) => (
            <button
              key={s}
              onClick={() => handleScoreChange(s)}
              className={clsx(
                'w-8 h-8 rounded-lg text-sm font-medium transition-colors',
                score === s
                  ? 'bg-primary-500 text-white'
                  : 'bg-white border border-slate-200 text-slate-600 hover:border-slate-300'
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-slate-500 mb-2 flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          Notes
        </p>
        <textarea
          value={notes}
          onChange={(e) => handleNotesChange(e.target.value)}
          placeholder="Add notes about this trace..."
          className="w-full px-3 py-2 text-sm border border-slate-200 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary-500"
          rows={2}
        />
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-slate-200">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={!hasChanges || saveMutation.isPending}
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            hasChanges
              ? 'bg-primary-600 text-white hover:bg-primary-700'
              : 'bg-slate-100 text-slate-400 cursor-not-allowed'
          )}
        >
          {saveMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
          Save
        </button>
        {label && (
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="flex items-center justify-center gap-1 px-3 py-2 text-sm font-medium text-red-600 bg-white border border-red-200 rounded-lg hover:bg-red-50 transition-colors"
          >
            {deleteMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
    </div>
  )
}
