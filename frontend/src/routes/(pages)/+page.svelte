<script lang="ts">
  import { Accordion, AccordionGroup, Button, Checkbox, Icon, Link } from '$components/dsfr'
  import HowItWorks from '$components/HowItWorks.svelte'
  import Newsletter from '$components/Newsletter.svelte'
  import * as env from '$env/static/public'
  import { getI18nContext } from '$lib/global.svelte'
  import { useLocalStorage } from '$lib/helpers/useLocalStorage.svelte'
  import { m } from '$lib/i18n/messages'
  import { getLocale } from '$lib/i18n/runtime'
  import { propsToAttrs, sanitize } from '$lib/utils/commons'

  const locale = getLocale()
  const i18nData = getI18nContext()
  const acceptTos = useLocalStorage('comparag:tos', false)
  let tosError = $state<string>()

  let PUBLIC_GIT_COMMIT = $state<string | null>((env as any).PUBLIC_GIT_COMMIT ?? null)

  if (PUBLIC_GIT_COMMIT) console.log(`Git commit: ${PUBLIC_GIT_COMMIT}`)

  $effect(() => {
    if (acceptTos.value) tosError = undefined
  })

  function handleRedirect() {
    if (acceptTos.value) {
      window.location.href = '/tool-arena'
    } else {
      tosError = m['home.intro.tos.error']()
    }
  }

  const localeOrDefault = $derived(['da', 'sv', 'en', 'fr'].includes(locale) ? locale : 'en')
  const utilyCards = $derived(
    (
      [
        {
          i18nKey: 'compare',
          src: `/home/comparer-${localeOrDefault}.png`,
          srcDark: `/home/comparer-dark-${localeOrDefault}.png`
        },
        { i18nKey: 'test', src: '/home/tester.png', srcDark: '/home/tester-dark.jpg' },
        {
          i18nKey: 'measure',
          src: `/home/mesurer-${localeOrDefault}.png`,
          srcDark: `/home/mesurer-dark-${localeOrDefault}.png`
        }
      ] as const
    ).map(({ i18nKey, ...card }) => ({
      ...card,
      title: m[`home.use.${i18nKey}.title`](),
      desc: m[`home.use.${i18nKey}.desc`](),
      alt: m[`home.use.${i18nKey}.alt`]()
    }))
  )

  const whyVoteCards = (
    [
      { i18nKey: 'prefs', src: '/home/prefs.svg' },
      { i18nKey: 'datasets', src: '/home/datasets.svg' },
      { i18nKey: 'finetune', src: '/home/finetune.svg' }
    ] as const
  ).map(({ i18nKey, ...card }) => ({
    ...card,
    title: m[`home.vote.steps.${i18nKey}.title`](),
    desc: m[`home.vote.steps.${i18nKey}.desc`]()
  }))

  const usageCards = (
    [
      { i18nKey: 'use', icon: 'i-ri-database-line' },
      { i18nKey: 'explore', icon: 'i-ri-search-line' },
      { i18nKey: 'educate', icon: 'i-ri-presentation-line' }
    ] as const
  ).map(({ i18nKey, ...card }) => ({
    ...card,
    title: m[`home.usage.${i18nKey}.title`](),
    desc: m[`home.usage.${i18nKey}.desc`]()
  }))

  const reducedFAQ = (
    [
      { id: 'usage', index: '2' },
      { id: 'models', index: '1' },
      { id: 'datasets', index: '2' },
      { id: 'ecology', index: '1' },
      { id: 'i18n', index: '1' }
    ] as const
  ).map(({ id, index }) => ({
    id,
    title: m[`faq.${id}.questions.${index}.title`](),
    desc: m[`faq.${id}.questions.${index}.desc`]()
  }))
</script>

<main id="content" class="">
  <div class="mistral-block-bar"></div>
  <section class="fr-container--fluid bg-light-grey pb-13 lg:pt-18 pt-10 lg:pb-28">
    <div
      class="fr-container gap-20 md:flex-row md:items-center md:gap-0 flex max-w-[1070px]! flex-col"
    >
      <div class="">
        <div class="mb-15 px-4 md:px-0">
          <div class="mb-10 md:w-[320px] md:max-w-[320px] max-w-[280px]">
            <h1 class="mb-5!">
              {@html sanitize(m['home.intro.title']({ props: 'class="text-primary"' }))}
            </h1>
            <p>{m['home.intro.desc']()}</p>
          </div>

          <Checkbox
            bind:checked={acceptTos.value}
            id="tos-home"
            label={m['home.intro.tos.accept']({
              linkProps: propsToAttrs({ href: '/modalites', target: '_blank' })
            })}
            help={m['home.intro.tos.help']()}
            error={tosError}
          />
        </div>

        <Button
          id="start_arena_btn"
          type="submit"
          text={m['header.startDiscussion']()}
          size="lg"
          class="md:max-w-[355px] w-full!"
          onclick={handleRedirect}
        />
      </div>
      <div class="bg-light-grey px-4 md:me-0 md:px-0 m-auto max-w-[545px] grow">
        <HowItWorks />
      </div>
    </div>
  </section>

  <section class="fr-container--fluid md:py-15 py-10">
    <div class="fr-container">
      <h3 class="mb-3! text-center">{m['home.use.title']()}</h3>
      <p class="mb-8! text-grey text-center">{m['home.use.desc']()}</p>

      <div class="gap-7 md:grid-cols-3 grid">
        {#each utilyCards as card, i (i)}
          <div class="cg-border">
            <img
              src={card.src}
              alt={card.alt}
              class="fr-responsive-img bg-light-grey sm:max-h-2/3 md:max-h-1/3 lg:max-h-1/2 xl:max-h-3/5 rounded-t-xl h-full! max-h-3/5 object-contain dark:hidden"
            />
            <img
              src={card.srcDark}
              alt={card.alt}
              class="fr-responsive-img bg-light-grey sm:max-h-2/3 md:max-h-1/3 lg:max-h-1/2 xl:max-h-3/5 rounded-t-xl hidden h-full! max-h-3/5 object-contain dark:block"
            />
            <div class="px-5 pb-7 pt-4 md:px-8 md:pb-10 md:pt-5">
              <h6 class="mb-1! md:mb-2!">{card.title}</h6>
              <p class="mb-0! text-grey">{card.desc}</p>
            </div>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <section class="fr-container--fluid bg-very-light-grey py-10 lg:py-14">
    <div class="fr-container">
      <div class="cg-border xl:p-13! bg-white px-4 py-10">
        <h4 class="mb-2! text-center">{m['home.vote.title']()}</h4>
        <p class="text-grey text-center">{m['home.vote.desc']()}</p>

        <div class="md:mt-13 mt-10 lg:flex-row flex flex-col text-center">
          {#each whyVoteCards as card, index (index)}
            <div class="basis-1/3">
              <div class="xl:h-4/7 lg:h-1/2">
                <img src={card.src} alt={card.title} width="72" height="72" class="mb-4 m-auto" />
                <h6 class="mb-1! mx-auto! max-w-[230px]">{card.title}</h6>
              </div>
              <p class="text-sm! text-grey m-auto! max-w-[280px]">{card.desc}</p>
            </div>
            {#if index < 2}
              <div class="arrow my-5 xl:-me-12 xl:-ms-12 relative shrink-0"></div>
            {/if}
          {/each}
        </div>

        <div class="lg:mt-19 mt-12 flex justify-center">
          <Link
            button
            hideExternalIcon
            size="lg"
            href="https://huggingface.co/datasets/ArthurSrz/comparag-tool-votes"
            text={m['home.vote.datasetAccess']()}
          />
        </div>
      </div>
    </div>
  </section>

  <section class="fr-container--fluid bg-light-grey py-10 lg:py-20">
    <div class="fr-container">
      <h3 class="mb-2! text-center">{m['home.usage.title']()}</h3>
      <p class="fr-mb-4w text-grey text-center">{m['home.vote.desc']()}</p>

      <div class="gap-8 md:grid-cols-3 grid">
        {#each usageCards as card, i (i)}
          <div class="cg-border bg-white p-5 lg:px-8 lg:pb-11 lg:pt-6">
            <Icon icon={card.icon} size="lg" block class="text-primary mb-4" />
            <h6 class="mb-2!">{card.title}</h6>
            <p class="mb-0! text-grey">{card.desc}</p>
          </div>
        {/each}
      </div>
    </div>
  </section>

  <section class="fr-container--fluid pb-18 lg:pb-25 pt-10 lg:pt-20">
    <div class="fr-container">
      <h3 class="mb-8! lg:mb-10! text-center">{m['home.faq.title']()}</h3>

      <AccordionGroup>
        {#each reducedFAQ as q (q.id)}
          <Accordion id={q.id} label={q.title}>
            {@html sanitize(q.desc)}
          </Accordion>
        {/each}
      </AccordionGroup>

      <div class="mt-8 lg:mt-11 text-center">
        <Link button size="lg" href="/product/faq" text={m['home.faq.discover']()} />
      </div>
    </div>
  </section>

  {#if locale === 'fr'}
    <Newsletter />
  {/if}
</main>

<style lang="postcss">
  .arrow {
    height: 62px;
    width: 16px;
    background-image: url('/home/arrow-h-mobile.svg');
    left: calc(50% - 8px);

    @media (min-width: 62em) {
      & {
        height: 16px;
        width: 125px;
        background-image: url('/home/arrow-h.svg');
        left: 0;
        margin-top: 36px;
      }
    }
  }
</style>
