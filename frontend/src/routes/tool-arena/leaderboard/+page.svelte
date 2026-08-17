<script lang="ts">
  import { api } from '$lib/fastapi-client'
  import { onMount } from 'svelte'
  import Header from '$components/header/Header.svelte'
  import SeoHead from '$components/SEOHead.svelte'
  import { m } from '$lib/i18n/messages'

  type ToolRanking = {
    tool_id: string
    elo: number
    score_p2_5: number
    score_p97_5: number
    n_match: number
    win_rate: number
    provisional: boolean
  }

  type LeaderboardResponse = {
    data_timestamp: number | null
    tools: ToolRanking[]
    by_task_type: Record<string, ToolRanking[]> | null
  }

  // Pool display metadata — order + label are defined here, not from the API,
  // so the UI stays stable even if new pools appear in the data.
  const POOLS: { key: string; label: string }[] = [
    { key: 'rag', label: m['toolArena.leaderboard.poolRag']() },
    { key: 'knowledge_capture', label: m['toolArena.leaderboard.poolKnowledgeCapture']() },
  ]

  let loading = $state(true)
  let error = $state<string | null>(null)
  // by_task_type from API; null means old backend (no per-pool data yet)
  let byTaskType = $state<Record<string, ToolRanking[]> | null>(null)
  // Fallback: global flat list (legacy or when by_task_type is missing)
  let allTools = $state<ToolRanking[]>([])

  // Active tab key; defaults to first pool with data
  let activePool = $state<string>('rag')

  onMount(async () => {
    try {
      const data = await api.request<LeaderboardResponse>('/tool-arena/leaderboard')
      allTools = [...data.tools].sort((a, b) => b.elo - a.elo)
      if (data.by_task_type) {
        byTaskType = Object.fromEntries(
          Object.entries(data.by_task_type).map(([pool, tools]) => [
            pool,
            [...tools].sort((a, b) => b.elo - a.elo),
          ])
        )
        // Auto-select first pool that has data
        const firstPoolWithData = POOLS.find(p => (byTaskType![p.key]?.length ?? 0) > 0)
        if (firstPoolWithData) activePool = firstPoolWithData.key
      }
    } catch (err) {
      error = (err as Error).message || m['toolArena.errorFallback']()
    } finally {
      loading = false
    }
  })

  // Tools shown in the current view: per-pool if available, otherwise global
  const displayedTools = $derived(
    byTaskType
      ? (byTaskType[activePool] ?? [])
      : allTools
  )

  // Pools that actually have data (for tab visibility)
  const activePools = $derived(
    byTaskType
      ? POOLS.filter(p => (byTaskType![p.key]?.length ?? 0) > 0)
      : []
  )
</script>

<SeoHead title={m['toolArena.leaderboard.title']()} />
<Header small />

<main class="bg-very-light-grey min-h-screen">
  <div class="fr-container py-10 md:py-16">
    <div class="mb-8 flex items-center justify-between">
      <h1 class="fr-h3 mb-0!">{m['toolArena.leaderboard.title']()}</h1>
      <a href="/tool-arena" class="fr-link fr-text--sm">
        &larr; {m['toolArena.leaderboard.backLink']()}
      </a>
    </div>

    {#if loading}
      <div class="text-center py-16">
        <p class="fr-text--sm text-grey animate-pulse">{m['toolArena.leaderboard.loading']()}</p>
      </div>

    {:else if error}
      <div class="cg-border rounded-lg bg-white p-6 text-center">
        <p class="fr-text--sm text-red-600 mb-0!">{error}</p>
      </div>

    {:else if allTools.length === 0}
      <div class="cg-border rounded-lg bg-white p-8 text-center">
        <p class="fr-text--sm text-grey mb-0!">
          {m['toolArena.leaderboard.empty']()}
        </p>
      </div>

    {:else}
      <!-- Pool tabs — only rendered when the backend sends by_task_type data -->
      {#if activePools.length > 1}
        <div class="flex gap-2 mb-4 border-b border-grey-200">
          {#each activePools as pool}
            <button
              type="button"
              class="px-4 py-2 fr-text--sm font-medium transition-colors border-b-2 -mb-px"
              class:border-primary={activePool === pool.key}
              class:text-primary={activePool === pool.key}
              class:border-transparent={activePool !== pool.key}
              class:text-grey={activePool !== pool.key}
              onclick={() => { activePool = pool.key }}
            >
              {pool.label}
              <span class="ml-1 fr-text--xs text-grey">
                ({byTaskType![pool.key]?.length ?? 0})
              </span>
            </button>
          {/each}
        </div>
        <p class="fr-text--xs text-grey mb-4">
          {m['toolArena.leaderboard.poolNote']()}
        </p>
      {/if}

      <div class="bg-white rounded-lg overflow-x-auto cg-border">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-grey-200">
              <th class="text-left px-4 py-3 font-semibold text-dark-grey">{m['toolArena.leaderboard.rank']()}</th>
              <th class="text-left px-4 py-3 font-semibold text-dark-grey">{m['toolArena.leaderboard.toolName']()}</th>
              <th class="text-right px-4 py-3 font-semibold text-dark-grey">{m['toolArena.leaderboard.eloScore']()}</th>
              <th class="text-right px-4 py-3 font-semibold text-dark-grey hidden md:table-cell">{m['toolArena.leaderboard.confidenceInterval']()}</th>
              <th class="text-right px-4 py-3 font-semibold text-dark-grey">{m['toolArena.leaderboard.matches']()}</th>
              <th class="text-right px-4 py-3 font-semibold text-dark-grey hidden sm:table-cell">{m['toolArena.leaderboard.winRate']()}</th>
            </tr>
          </thead>
          <tbody>
            {#each displayedTools as tool, i}
              <tr class="border-b border-grey-100 last:border-0 hover:bg-very-light-grey transition-colors">
                <td class="px-4 py-3 font-semibold text-grey">{i + 1}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="font-medium">{tool.tool_id}</span>
                    {#if tool.provisional}
                      <span
                        class="fr-text--xs px-1.5 py-0.5 rounded"
                        style="background-color: #f5f5fe; color: #6b7280; border: 1px solid #e5e7eb;"
                      >
                        {m['toolArena.leaderboard.provisional']()}
                      </span>
                    {/if}
                  </div>
                </td>
                <td class="px-4 py-3 text-right font-mono">
                  {tool.elo.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-right text-grey hidden md:table-cell font-mono fr-text--sm">
                  {tool.score_p2_5.toFixed(1)} – {tool.score_p97_5.toFixed(1)}
                </td>
                <td class="px-4 py-3 text-right text-grey">{tool.n_match}</td>
                <td class="px-4 py-3 text-right text-grey hidden sm:table-cell">
                  {(tool.win_rate * 100).toFixed(1)}%
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="fr-text--xs text-grey mt-3">
        {m['toolArena.leaderboard.eloExplanation']()}
      </p>
    {/if}
  </div>
</main>
