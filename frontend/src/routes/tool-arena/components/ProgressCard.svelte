<script lang="ts">
  import type { SSEEvent } from '../lib/sse-client'

  interface Props {
    event: SSEEvent | null
  }

  let { event }: Props = $props()

  function labelFor(e: SSEEvent | null): string {
    if (!e) return '—'
    switch (e.type) {
      case 'ingest_start':
        return 'Ingesting…'
      case 'ingest_done':
        return e.cache_hit ? 'Cache hit' : 'Ingest complete'
      case 'retrieval_start':
        return 'Retrieving…'
      case 'retrieval_done':
        return 'Retrieval complete'
      case 'mediation_start':
        return 'Generating answer…'
      case 'mediation_done':
        return 'Answer ready'
      case 'result':
        return 'Done'
      case 'error':
        return 'Error'
      default:
        return e.type
    }
  }
</script>

<div class="progress-card">
  <span data-testid="progress-label">{labelFor(event)}</span>
</div>

<style>
  .progress-card {
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    background: var(--background-alt-grey, #f6f6f6);
    font-size: 0.875rem;
  }
</style>
