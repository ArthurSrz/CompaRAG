<!--
  BUT : un bras d'entretien knowledge_capture — l'Interviewer A ou B pose ses
  questions, l'expert (l'utilisateur) répond dans CE panneau uniquement.
  Les deux panneaux sont indépendants par construction (l'Interview est un
  variant de l'ontologie) : rien de ce qui est saisi ici n'atteint l'autre bras.
-->
<script lang="ts">
  import MarkdownCode from '$lib/components/markdown/MarkdownCode.svelte'
  import { m } from '$lib/i18n/messages'

  type Message = { role: 'interviewer' | 'expert'; content: string }

  let {
    label,
    messages,
    turn,
    maxTurns,
    done = false,
    error = null,
    busy = false,
    onreply,
    onfinish
  }: {
    label: 'A' | 'B'
    messages: Message[]
    turn: number
    maxTurns: number
    done?: boolean
    error?: string | null
    busy?: boolean
    onreply: (answer: string) => void
    onfinish: () => void
  } = $props()

  let draft = $state('')
  let scroller = $state<HTMLElement | undefined>(undefined)

  const inputDisabled = $derived(busy || done || !!error)

  $effect(() => {
    // Autoscroll on new messages so the latest question stays visible.
    void messages.length
    if (scroller) scroller.scrollTop = scroller.scrollHeight
  })

  function submit(e: SubmitEvent) {
    e.preventDefault()
    const answer = draft.trim()
    if (!answer || inputDisabled) return
    draft = ''
    onreply(answer)
  }
</script>

<div class="cg-border rounded-lg! bg-white flex w-full flex-col overflow-hidden">
  <div class="flex items-center justify-between px-4 py-3 border-b border-solid border-gray-200">
    <div class="flex items-center">
      <div class="c-bot-disk-{label.toLowerCase()}"></div>
      <p class="ms-1! mb-0! font-bold">
        {label === 'A' ? m['toolArena.interview.panelA']() : m['toolArena.interview.panelB']()}
      </p>
    </div>
    <span class="fr-text--sm text-grey mb-0!">
      {m['toolArena.interview.turnCounter']()} {Math.min(turn, maxTurns)}/{maxTurns}
    </span>
  </div>

  <div bind:this={scroller} class="flex-1 overflow-y-auto p-4 flex flex-col gap-3" style="max-height: min(62vh, 36rem); min-height: 14rem;">
    {#each messages as message}
      {#if message.role === 'interviewer'}
        <div class="fr-text--sm text-dark-grey interview-md">
          <MarkdownCode message={message.content} kind="bot" line_breaks={true} />
        </div>
      {:else}
        <div class="self-end max-w-[85%] rounded-lg bg-light-grey px-3 py-2">
          <p class="fr-text--sm text-dark-grey mb-0! whitespace-pre-wrap">{message.content}</p>
        </div>
      {/if}
    {/each}
    {#if busy}
      <p class="fr-text--sm text-grey italic mb-0! animate-pulse">{m['toolArena.interview.waiting']()}</p>
    {/if}
    {#if error}
      <p class="fr-text--sm text-grey italic mb-0!">{m['toolArena.interview.errorArm']()}</p>
    {:else if done}
      <p class="fr-text--sm text-grey italic mb-0!">{m['toolArena.interview.armDone']()}</p>
    {/if}
  </div>

  <form onsubmit={submit} class="border-t border-solid border-gray-200 p-3 flex gap-2 items-end">
    <textarea
      class="fr-input cg-border rounded-md! bg-white! border-solid! flex-1"
      rows="2"
      bind:value={draft}
      placeholder={m['toolArena.interview.inputPlaceholder']()}
      disabled={inputDisabled}
      onkeydown={(e) => {
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
          e.preventDefault()
          e.currentTarget.form?.requestSubmit()
        }
      }}
    ></textarea>
    <div class="flex flex-col gap-2">
      <button
        type="submit"
        class="fr-btn fr-btn--sm"
        disabled={inputDisabled || draft.trim().length === 0}
      >
        {m['toolArena.interview.send']()}
      </button>
      <button
        type="button"
        class="fr-btn fr-btn--sm fr-btn--secondary"
        disabled={inputDisabled || messages.length === 0}
        onclick={onfinish}
      >
        {m['toolArena.interview.finishEarly']()}
      </button>
    </div>
  </form>
</div>

<style>
  .interview-md :global(ul),
  .interview-md :global(ol) {
    padding-left: 1.5rem;
    margin-bottom: 0.5rem;
  }
  .interview-md :global(ul) { list-style-type: disc; }
  .interview-md :global(ol) { list-style-type: decimal; }

  /* Les intervieweurs émettent des #/## : à taille pleine, un h1 écrase la
     bulle de chat. On les ramène à une hiérarchie lisible en contexte. */
  .interview-md :global(h1) { font-size: 1.05rem; margin: 0.5rem 0 0.25rem; }
  .interview-md :global(h2) { font-size: 0.98rem; margin: 0.5rem 0 0.25rem; }
  .interview-md :global(h3),
  .interview-md :global(h4) { font-size: 0.92rem; margin: 0.4rem 0 0.2rem; }
  .interview-md :global(p) { margin-bottom: 0.5rem; }
  .interview-md :global(hr) { margin: 0.6rem 0; }
</style>
