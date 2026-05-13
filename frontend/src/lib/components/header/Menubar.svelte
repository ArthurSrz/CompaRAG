<script lang="ts">
  import { page } from '$app/state'
  import { m } from '$lib/i18n/messages'
  import { getLocale } from '$lib/i18n/runtime'

  const locale = getLocale()
  // Navigation links for both desktop and mobile menus.
  // "Classement" points at the Tool Arena leaderboard since CompaRAG is the
  // RAG-tool comparator; the legacy /ranking route still exists but renders
  // the LLM ranking which has no data on this deployment.
  const navLinks = [
    { href: '/', label: m['seo.titles.home']() },
    { href: '/product', label: m['seo.titles.product']() },
    { href: '/tool-arena/leaderboard', label: m['seo.titles.ranking']() },
    { href: '/tool-arena', label: m['seo.titles.tool-arena']() },
    { href: '/datasets', label: m['seo.titles.datasets']() }
  ]

  function isCurrentPage(path: string, href: string) {
    if (path.includes('product')) return href.includes('product')
    return path === href
  }
</script>

<nav class="fr-nav" data-fr-js-navigation="true">
  <ul class="fr-nav__list fr-container">
    {#each navLinks as link (link.href)}
      <li class="fr-nav__item" data-fr-js-navigation-item="true">
        <a
          href={link.href}
          target="_self"
          aria-controls="modal-header__menu"
          class="fr-nav__link"
          aria-current={isCurrentPage(page.url.pathname, link.href) ? 'true' : undefined}
          data-fr-js-modal-button="true"
        >
          {link.label}
        </a>
      </li>
    {/each}
  </ul>
</nav>
