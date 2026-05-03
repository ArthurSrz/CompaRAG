<script lang="ts">
  import { create_marked, sanitize, copy } from '$lib/components/markdown/utils'
  import 'prismjs/themes/prism.css'

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

  // Reuse the project's existing markdown pipeline (marked + prism highlighting,
  // then amuchina sanitization). Disable header anchors here — the cards are
  // ephemeral comparison views, not navigable docs.
  const marked = create_marked({ header_links: false, line_breaks: true })

  const rendered_html = $derived.by(() => {
    if (!result) return ''
    const raw_html = marked.parse(result, { async: false }) as string
    return sanitize(raw_html)
  })
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
    <div class="fr-text--sm text-dark-grey markdown-body" use:copy>
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html rendered_html}
    </div>
  {:else}
    <div class="py-6">
      <p class="fr-text--sm text-grey mb-0!">No result</p>
    </div>
  {/if}
</div>

<style>
  .markdown-body :global(h1),
  .markdown-body :global(h2),
  .markdown-body :global(h3) {
    font-weight: 700;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
  }
  .markdown-body :global(h1) { font-size: 1.25rem; }
  .markdown-body :global(h2) { font-size: 1.125rem; }
  .markdown-body :global(h3) { font-size: 1rem; }
  .markdown-body :global(p) { margin-bottom: 0.5rem; line-height: 1.5; }
  .markdown-body :global(ul),
  .markdown-body :global(ol) {
    padding-left: 1.5rem;
    margin-bottom: 0.5rem;
  }
  .markdown-body :global(ul) { list-style-type: disc; }
  .markdown-body :global(ol) { list-style-type: decimal; }
  .markdown-body :global(li) { margin-bottom: 0.25rem; }
  .markdown-body :global(li > ul),
  .markdown-body :global(li > ol) { margin-top: 0.25rem; margin-bottom: 0; }
  .markdown-body :global(code) {
    background: #f4f4f4;
    padding: 0.125rem 0.25rem;
    border-radius: 0.25rem;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.875em;
  }
  .markdown-body :global(pre) {
    background: #f4f4f4;
    padding: 0.75rem;
    border-radius: 0.375rem;
    overflow-x: auto;
    margin-bottom: 0.5rem;
  }
  .markdown-body :global(pre code) {
    background: transparent;
    padding: 0;
  }
  .markdown-body :global(strong) { font-weight: 700; }
  .markdown-body :global(em) { font-style: italic; }
  .markdown-body :global(a) {
    color: #3558a2;
    text-decoration: underline;
  }
  .markdown-body :global(blockquote) {
    border-left: 3px solid #ddd;
    padding-left: 0.75rem;
    color: #555;
    margin: 0.5rem 0;
  }
</style>
