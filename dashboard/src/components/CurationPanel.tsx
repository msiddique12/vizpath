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
  { value: 'excellent', color: 'bg-green-900/50 text-green-400 border-green-800' },
  { value: 'good', color: 'bg-blue-900/50 text-blue-400 border-blue-800' },
  { value: 'needs_improvement', color: 'bg-amber-900/50 text-amber-400 border-amber-800' },
  { value: 'failure', color: 'bg-red-900/50 text-red-400 border-red-800' },
  { value: 'interesting', color: 'bg-purple-900/50 text-purple-400 border-purple-800' },
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
        <Loader2 className="h-5 w-5 text-muted-400 animate-spin" />
      </div>
    )
  }

  return (
    <div className="bg-dark-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-muted-200 flex items-center gap-2">
          <Tag className="h-4 w-4" />
          Curation
        </h3>
        {label && (
          <span className="text-xs text-muted-400">
            {label.exported ? 'Exported' : 'Not exported'}
          </span>
        )}
      </div>

      <div>
        <p className="text-xs text-muted-400 mb-2">Label</p>
        <div className="flex flex-wrap gap-2">
          {LABELS.map(({ value, color }) => (
            <button
              key={value}
              onClick={() => handleLabelClick(value)}
              className={clsx(
                'px-2.5 py-1 text-xs font-medium rounded-full border transition-all',
                selectedLabel === value
                  ? `${color} ring-2 ring-offset-1 ring-primary-400`
                  : 'bg-dark-900 text-muted-300 border-dark-700 hover:border-muted-400'
              )}
            >
              {value.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-muted-400 mb-2 flex items-center gap-1">
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
                  : 'bg-dark-900 border border-dark-700 text-muted-300 hover:border-muted-400'
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-xs text-muted-400 mb-2 flex items-center gap-1">
          <MessageSquare className="h-3 w-3" />
          Notes
        </p>
        <textarea
          value={notes}
          onChange={(e) => handleNotesChange(e.target.value)}
          placeholder="Add notes about this trace..."
          className="w-full px-3 py-2 text-sm bg-dark-900 text-muted-100 border border-dark-700 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 placeholder:text-muted-500"
          rows={2}
        />
      </div>

      <div className="flex items-center gap-2 pt-2 border-t border-dark-700">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={!hasChanges || saveMutation.isPending}
          className={clsx(
            'flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-lg transition-colors',
            hasChanges
              ? 'bg-primary-600 text-white hover:bg-primary-700'
              : 'bg-dark-700 text-muted-400 cursor-not-allowed'
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
            className="flex items-center justify-center gap-1 px-3 py-2 text-sm font-medium text-red-400 bg-dark-900 border border-red-800 rounded-lg hover:bg-red-900/30 transition-colors"
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
