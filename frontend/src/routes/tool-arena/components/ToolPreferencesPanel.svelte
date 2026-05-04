<script lang="ts">
  import { m } from '$lib/i18n/messages'

  // 1-5 goal-attainment rating per side. ``null`` until the user clicks a star.
  // The component is bindable so the parent (ToolVoteArea) can submit the
  // payload as part of /tool-arena/vote.
  let {
    side,
    rating = $bindable(null),
    disabled = false
  }: {
    side: 'a' | 'b'
    rating: number | null
    disabled?: boolean
  } = $props()

  const STARS: ReadonlyArray<1 | 2 | 3 | 4 | 5> = [1, 2, 3, 4, 5] as const

  function pick(value: 1 | 2 | 3 | 4 | 5) {
    if (disabled) return
    rating = rating === value ? null : value
  }

  // i18n with English fallback so a missing key never blanks the UI.
  function t(key: string, fallback: string): string {
    try {
      const fn = (m as unknown as Record<string, () => string>)[key]
      return fn ? fn() : fallback
    } catch {
      return fallback
    }
  }

  const heading = $derived(side === 'a' ? 'Tool A' : 'Tool B')
  const question = t(
    'vote.goalRating.question',
    'Cette réponse atteint-elle votre objectif ?'
  )
  function ariaLabel(n: number): string {
    return t(`vote.goalRating.aria_${n}`, `${n} étoile${n > 1 ? 's' : ''} sur 5`)
  }
</script>

<fieldset class="cg-border rounded-lg p-4">
  <legend class="fr-text--sm font-medium px-2">{heading}</legend>

  <p class="fr-text--xs text-grey mb-3">{question}</p>

  <div role="radiogroup" aria-label={question} class="flex gap-1.5">
    {#each STARS as value (value)}
      <button
        type="button"
        role="radio"
        aria-checked={rating === value}
        aria-label={ariaLabel(value)}
        class="star"
        class:filled={rating !== null && value <= rating}
        {disabled}
        onclick={() => pick(value)}
      >
        <!-- Solid star when filled, outline otherwise. -->
        {#if rating !== null && value <= rating}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="28"
            height="28"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01z"
            />
          </svg>
        {:else}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="28"
            height="28"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path
              d="M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 22 12 18.27 5.82 22 7 14.14l-5-4.87 6.91-1.01z"
            />
          </svg>
        {/if}
      </button>
    {/each}
  </div>
</fieldset>

<style>
  .star {
    background: none;
    border: none;
    padding: 2px;
    cursor: pointer;
    color: var(--grey-625-425);
    transition: color 0.12s, transform 0.08s;
  }
  .star:hover:not(:disabled),
  .star:focus-visible {
    color: var(--blue-france-main-525);
    transform: scale(1.05);
  }
  .star.filled {
    color: #f5a623; /* warm amber matching the DSFR accent palette */
  }
  .star:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .star:focus-visible {
    outline: 2px solid var(--outline-color);
    outline-offset: 2px;
    border-radius: 4px;
  }
</style>
