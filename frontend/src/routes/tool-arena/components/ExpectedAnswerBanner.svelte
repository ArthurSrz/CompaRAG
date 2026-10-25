<script lang="ts">
  interface Props {
    // The question the duel was run on. Shown next to the expected answer:
    // at vote time the form is gone, and judging two answers without the
    // question in front of you is guesswork.
    question?: string | null
    expectedAnswer: string | null
  }

  let { question = null, expectedAnswer }: Props = $props()

  const askedQuestion = $derived((question ?? '').trim())
  const trimmed = $derived((expectedAnswer ?? '').trim())
</script>

{#if askedQuestion.length > 0 || trimmed.length > 0}
  <div
    class="expected-answer-banner cg-border bg-white p-4 rounded-md mb-6"
    data-testid="expected-answer-banner"
  >
    {#if askedQuestion.length > 0}
      <p class="fr-text--sm font-bold mb-2!">Question posée</p>
      <p class="mb-4! whitespace-pre-wrap">{askedQuestion}</p>
    {/if}
    {#if trimmed.length > 0}
      <p class="fr-text--sm font-bold mb-2!">Réponse attendue</p>
      <p class="mb-0! whitespace-pre-wrap">{trimmed}</p>
    {/if}
  </div>
{/if}

<style>
  .expected-answer-banner {
    border-left: 4px solid var(--background-action-high-grey, #3a3a3a);
  }
</style>
