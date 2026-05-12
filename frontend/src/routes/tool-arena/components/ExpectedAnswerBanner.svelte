<script lang="ts">
  interface Props {
    expectedAnswer: string | null
  }

  let { expectedAnswer }: Props = $props()

  const trimmed = $derived((expectedAnswer ?? '').trim())
</script>

{#if trimmed.length > 0}
  <div
    class="expected-answer-banner cg-border bg-white p-4 rounded-md mb-6"
    data-testid="expected-answer-banner"
  >
    <p class="fr-text--sm font-bold mb-2!">Réponse attendue</p>
    <p class="mb-0! whitespace-pre-wrap">{trimmed}</p>
  </div>
{/if}

<style>
  .expected-answer-banner {
    border-left: 4px solid var(--background-action-high-grey, #3a3a3a);
  }
</style>
