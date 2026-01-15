import { useEffect, useRef, useMemo } from 'react'
import * as d3 from 'd3'
import { Span, SpanType } from '@/lib/types'

const SPAN_COLORS: Record<SpanType, string> = {
  llm: '#8b5cf6',
  tool: '#3b82f6',
  agent: '#22c55e',
  retrieval: '#eab308',
  chain: '#f97316',
  custom: '#94a3b8',
}

interface DAGNode {
  id: string
  name: string
  span: Span
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}

interface DAGLink {
  source: string | DAGNode
  target: string | DAGNode
}

interface DAGViewProps {
  spans: Span[]
  width?: number
  height?: number
}

export default function DAGView({ spans, width = 800, height = 500 }: DAGViewProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  const { nodes, links } = useMemo(() => {
    const nodeMap = new Map<string, DAGNode>()
    const linkList: DAGLink[] = []

    spans.forEach((span) => {
      nodeMap.set(span.id, {
        id: span.id,
        name: span.name,
        span,
      })
    })

    spans.forEach((span) => {
      if (span.parent_id && nodeMap.has(span.parent_id)) {
        linkList.push({
          source: span.parent_id,
          target: span.id,
        })
      }
    })

    return {
      nodes: Array.from(nodeMap.values()),
      links: linkList,
    }
  }, [spans])

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()

    const g = svg.append('g')

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 3])
      .on('zoom', (event) => {
        g.attr('transform', event.transform)
      })

    svg.call(zoom)

    svg.append('defs').append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '-0 -5 10 10')
      .attr('refX', 20)
      .attr('refY', 0)
      .attr('orient', 'auto')
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .append('path')
      .attr('d', 'M 0,-5 L 10,0 L 0,5')
      .attr('fill', '#94a3b8')

    const simulation = d3.forceSimulation<DAGNode>(nodes)
      .force('link', d3.forceLink<DAGNode, DAGLink>(links)
        .id((d) => d.id)
        .distance(100)
      )
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40))

    const link = g.append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#cbd5e1')
      .attr('stroke-width', 2)
      .attr('marker-end', 'url(#arrowhead)')

    const drag = d3.drag<SVGGElement, DAGNode>()
      .on('start', (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        d.fx = d.x
        d.fy = d.y
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        if (!event.active) simulation.alphaTarget(0)
        d.fx = null
        d.fy = null
      })

    const node = g.append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(nodes)
      .join('g')
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      .call(drag as any)

    node.append('circle')
      .attr('r', (d) => {
        const duration = d.span.duration_ms || 100
        return Math.min(Math.max(Math.sqrt(duration) / 2, 15), 40)
      })
      .attr('fill', (d) => SPAN_COLORS[d.span.span_type as SpanType] || SPAN_COLORS.custom)
      .attr('stroke', (d) => d.span.status === 'error' ? '#ef4444' : '#fff')
      .attr('stroke-width', (d) => d.span.status === 'error' ? 3 : 2)

    node.append('text')
      .text((d) => d.name.length > 15 ? d.name.slice(0, 12) + '...' : d.name)
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => {
        const duration = d.span.duration_ms || 100
        const radius = Math.min(Math.max(Math.sqrt(duration) / 2, 15), 40)
        return radius + 15
      })
      .attr('font-size', '11px')
      .attr('fill', '#475569')

    const tooltip = d3.select('body').append('div')
      .attr('class', 'dag-tooltip')
      .style('position', 'absolute')
      .style('visibility', 'hidden')
      .style('background', 'white')
      .style('border', '1px solid #e2e8f0')
      .style('border-radius', '6px')
      .style('padding', '8px 12px')
      .style('font-size', '12px')
      .style('box-shadow', '0 4px 6px -1px rgb(0 0 0 / 0.1)')
      .style('z-index', '1000')

    node.on('mouseover', (_event, d) => {
      const duration = d.span.duration_ms
      const durationStr = duration
        ? duration < 1000 ? `${duration.toFixed(0)}ms` : `${(duration / 1000).toFixed(2)}s`
        : 'running'

      tooltip
        .style('visibility', 'visible')
        .html(`
          <div style="font-weight: 600; margin-bottom: 4px;">${d.name}</div>
          <div style="color: #64748b;">Type: ${d.span.span_type}</div>
          <div style="color: #64748b;">Duration: ${durationStr}</div>
          ${d.span.tokens ? `<div style="color: #64748b;">Tokens: ${d.span.tokens}</div>` : ''}
          ${d.span.error ? `<div style="color: #ef4444;">Error: ${d.span.error}</div>` : ''}
        `)
    })
    .on('mousemove', (event) => {
      tooltip
        .style('top', (event.pageY - 10) + 'px')
        .style('left', (event.pageX + 10) + 'px')
    })
    .on('mouseout', () => {
      tooltip.style('visibility', 'hidden')
    })

    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as DAGNode).x || 0)
        .attr('y1', (d) => (d.source as DAGNode).y || 0)
        .attr('x2', (d) => (d.target as DAGNode).x || 0)
        .attr('y2', (d) => (d.target as DAGNode).y || 0)

      node.attr('transform', (d) => `translate(${d.x || 0},${d.y || 0})`)
    })

    return () => {
      simulation.stop()
      tooltip.remove()
    }
  }, [nodes, links, width, height])

  if (spans.length === 0) {
    return <p className="text-slate-500 text-sm">No spans to visualize.</p>
  }

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="border border-slate-200 rounded-lg bg-slate-50"
      />
      <div className="absolute bottom-4 left-4 flex items-center gap-3 bg-white/90 px-3 py-2 rounded-lg border border-slate-200 text-xs">
        {Object.entries(SPAN_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1">
            <div className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-slate-600">{type}</span>
          </div>
        ))}
      </div>
      <div className="absolute top-4 right-4 text-xs text-slate-500 bg-white/90 px-2 py-1 rounded border border-slate-200">
        Drag to move • Scroll to zoom
      </div>
    </div>
  )
}
