<!--
  BUT : afficher un encart d'inscription à l'infolettre du projet, rendu via
  un iframe Tally.so. Le formulaire Tally lui-même (titre, libellés des
  champs, libellé de consentement) est défini SUR TALLY.SO — pas dans ce
  repo. Le formulaire pointé ci-dessous (zxKR40) est hérité du fork upstream
  et mentionne encore « compar:IA » dans la case de consentement ; pour
  corriger ce libellé il faut soit créer un nouveau formulaire Tally et
  remplacer l'URL, soit éditer zxKR40 sur tally.so.

  TODO: replace zxKR40 by a CompaRAG-owned Tally form.
-->
<script lang="ts">
  import { Icon, Link } from '$components/dsfr'
</script>

<div class="mt-3 text-center">
  <div class="bg-light-info p-3 inline-block">
    <Link href="#" text="Haut de page" icon="arrow-up-line" class="pb-1!" />
  </div>
</div>
<section class="fr-container--fluid bg-light-info">
  <div class="fr-container pb-10 pt-8">
    <div class="mb-4">
      <h5 class="mb-2! flex items-center">
        <Icon icon="i-ri-mail-line" size="lg" block class="text-primary me-2" />
        Abonnez-vous à notre lettre d'information
      </h5>
      <p class="text-sm!">
        Retrouvez les dernières actualités du projet : partenariats, intégration de nouveaux
        outils RAG, publications de jeux de données et nouvelles fonctionnalités !
      </p>
    </div>
    <div>
      <iframe
        data-tally-src="https://tally.so/embed/zxKR40?alignLeft=1&hideTitle=1&transparentBackground=1&dynamicHeight=1"
        loading="lazy"
        width="100%"
        height="380"
        frameborder="0"
        marginheight="0"
        marginwidth="0"
        title="Infolettre CompaRAG"
        class="outline-none! dark:invert"
      ></iframe>
    </div>
  </div>
</section>

<style>
  iframe {
    color-scheme: light;
  }
</style>
