<script lang="ts">
  import MarkdownCode from '$lib/components/markdown/MarkdownCode.svelte'

  let {
    label,
    result,
    error,
    loading = false
  }: {
    label: string
    result: string | null
    error: string | null
    loading?: boolean
  } = $props()
</script>

<div class="cg-border gap-4 rounded-lg! bg-white p-4 md:rounded-lg md:px-6 md:py-8 flex w-full flex-col">
  <div class="flex items-center">
    <div class="c-bot-disk-{label.toLowerCase()}"></div>
    <p class="ms-1! mb-0! font-bold">Tool {label}</p>
  </div>

  {#if loading}
    <div class="py-6">
      <p class="fr-text--sm text-grey animate-pulse mb-0!">Comparing...</p>
    </div>
  {:else if error}
    <div class="cg-border rounded-lg! p-4 bg-very-light-grey">
      <p class="fr-text--sm text-grey italic mb-0!">Tool encountered an error</p>
    </div>
  {:else if result}
    <div class="fr-text--sm text-dark-grey tool-arena-md">
      <MarkdownCode message={result} kind="bot" line_breaks={true} />
    </div>
  {:else}
    <div class="py-6">
      <p class="fr-text--sm text-grey mb-0!">No result</p>
    </div>
  {/if}
</div>

<style>
  /* Constrain wide tables to the card width with horizontal scroll. */
  .tool-arena-md :global(table) {
    display: block;
    overflow-x: auto;
    max-width: 100%;
  }
  .tool-arena-md :global(thead) {
    background: #f4f4f4;
  }
  .tool-arena-md :global(tr:nth-child(even) td) {
    background: #fafafa;
  }
  .tool-arena-md :global(th),
  .tool-arena-md :global(td) {
    padding: 0.4rem 0.6rem;
    text-align: left;
    vertical-align: top;
  }
  .tool-arena-md :global(ul),
  .tool-arena-md :global(ol) {
    padding-left: 1.5rem;
    margin-bottom: 0.5rem;
  }
  .tool-arena-md :global(ul) { list-style-type: disc; }
  .tool-arena-md :global(ol) { list-style-type: decimal; }
</style>
