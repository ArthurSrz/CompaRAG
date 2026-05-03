<script lang="ts">
  import { m } from '$lib/i18n/messages'

  export type ToolPrefKey =
    | 'useful'
    | 'complete'
    | 'creative'
    | 'clear_formatting'
    | 'incorrect'
    | 'superficial'
    | 'instructions_not_followed'

  export const POSITIVE_PREFS: ToolPrefKey[] = [
    'useful',
    'complete',
    'creative',
    'clear_formatting'
  ]
  export const NEGATIVE_PREFS: ToolPrefKey[] = [
    'incorrect',
    'superficial',
    'instructions_not_followed'
  ]

  let {
    side,
    selected = $bindable([]),
    disabled = false
  }: {
    side: 'a' | 'b'
    selected: ToolPrefKey[]
    disabled?: boolean
  } = $props()

  function toggle(pref: ToolPrefKey) {
    if (disabled) return
    selected = selected.includes(pref)
      ? selected.filter((p) => p !== pref)
      : [...selected, pref]
  }

  // i18n fallback labels (lookups happen at render time and may be missing
  // in older locale files — fall back to the English key).
  function label(pref: ToolPrefKey, polarity: 'positive' | 'negative'): string {
    const key = `vote.choices.${polarity}.${pref}` as const
    try {
      const fn = (m as unknown as Record<string, () => string>)[key]
      return fn ? fn() : pref.replace(/_/g, ' ')
    } catch {
      return pref.replace(/_/g, ' ')
    }
  }
</script>

<fieldset class="cg-border rounded-lg p-4">
  <legend class="fr-text--sm font-medium px-2">
    {side === 'a' ? 'Tool A' : 'Tool B'}
  </legend>

  <div class="flex flex-col gap-3 md:flex-row md:gap-6">
    <div class="flex-1">
      <p class="fr-text--xs text-grey mb-2">
        {m['vote.choices.positive.question']?.() ?? 'Positive aspects'}
      </p>
      <div class="flex flex-wrap gap-2">
        {#each POSITIVE_PREFS as pref (pref)}
          <button
            type="button"
            class="pref-chip"
            class:selected={selected.includes(pref)}
            {disabled}
            onclick={() => toggle(pref)}
          >
            {label(pref, 'positive')}
          </button>
        {/each}
      </div>
    </div>

    <div class="flex-1">
      <p class="fr-text--xs text-grey mb-2">
        {m['vote.choices.negative.question']?.() ?? 'Negative aspects'}
      </p>
      <div class="flex flex-wrap gap-2">
        {#each NEGATIVE_PREFS as pref (pref)}
          <button
            type="button"
            class="pref-chip"
            class:selected={selected.includes(pref)}
            {disabled}
            onclick={() => toggle(pref)}
          >
            {label(pref, 'negative')}
          </button>
        {/each}
      </div>
    </div>
  </div>
</fieldset>

<style>
  .pref-chip {
    border: 1px solid var(--grey-925-125);
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 0.85rem;
    background: white;
    cursor: pointer;
    transition: all 0.15s;
  }
  .pref-chip:hover:not(:disabled) {
    border-color: var(--blue-france-main-525);
  }
  .pref-chip.selected {
    background: var(--blue-france-975-75);
    border-color: var(--blue-france-main-525);
    color: var(--blue-france-main-525);
  }
  .pref-chip:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
