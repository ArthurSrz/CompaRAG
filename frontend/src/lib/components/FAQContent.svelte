<script lang="ts">
  import { Accordion, AccordionGroup, Tabs } from '$components/dsfr'
  import { m } from '$lib/i18n/messages'
  import { sanitize } from '$lib/utils/commons'

  // Five tabs, each focused on a domain question users actually ask about
  // CompaRAG's RAG-comparison flow — see locales/messages/*.json#faq.
  const tabs = [
    {
      id: 'fairness',
      label: m['faq.fairness.title'](),
      qs: (['1'] as const).map((q) => ({
        title: m[`faq.fairness.questions.${q}.title`](),
        desc: m[`faq.fairness.questions.${q}.desc`]()
      }))
    },
    {
      id: 'comparison',
      label: m['faq.comparison.title'](),
      qs: (['1'] as const).map((q) => ({
        title: m[`faq.comparison.questions.${q}.title`](),
        desc: m[`faq.comparison.questions.${q}.desc`]()
      }))
    },
    {
      id: 'rag',
      label: m['faq.rag.title'](),
      qs: (['1'] as const).map((q) => ({
        title: m[`faq.rag.questions.${q}.title`](),
        desc: m[`faq.rag.questions.${q}.desc`]()
      }))
    },
    {
      id: 'data',
      label: m['faq.data.title'](),
      qs: (['1'] as const).map((q) => ({
        title: m[`faq.data.questions.${q}.title`](),
        desc: m[`faq.data.questions.${q}.desc`]()
      }))
    },
    {
      id: 'extend',
      label: m['faq.extend.title'](),
      qs: (['1'] as const).map((q) => ({
        title: m[`faq.extend.questions.${q}.title`](),
        desc: m[`faq.extend.questions.${q}.desc`]()
      }))
    }
  ]
</script>

<Tabs {tabs} noBorders kind="nav" label={m['faq.title']()}>
  {#snippet tab({ id })}
    {#each tabs as tab (tab.id)}
      {#if id === tab.id}
        <AccordionGroup>
          {#each tab.qs as q, i (`${tab.id}-${i}`)}
            <Accordion id={`${tab.id}-${i}`} label={q.title}>
              {@html sanitize(q.desc)}
            </Accordion>
          {/each}
        </AccordionGroup>
      {/if}
    {/each}
  {/snippet}
</Tabs>
