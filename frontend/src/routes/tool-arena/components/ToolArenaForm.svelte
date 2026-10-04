<script lang="ts">
  import { browser, dev } from '$app/environment'
  import { env as publicEnv } from '$env/dynamic/public'
  import { Button } from '$components/dsfr'
  import { m } from '$lib/i18n/messages'

  // Same resolution as +page.svelte:65-69 — keeps extract calls on the
  // same origin as POST /tool-arena/compare.
  function backendBase(): string {
    if (!browser) return publicEnv.PUBLIC_API_LOCAL_URL || publicEnv.PUBLIC_API_URL || 'http://localhost:8001'
    if (dev || publicEnv.PUBLIC_API_DEV_MODE === 'true') return 'http://localhost:8001'
    return publicEnv.PUBLIC_API_URL || window.location.origin || 'http://localhost:8001'
  }

  // Unified upload cap across all supported formats. The previous 500KB/5MB
  // split conflated "raw upload bytes" with "extracted text size": a 5MB PDF
  // typically extracts to <500KB of text, while a 500KB .txt is ALL text.
  // Now every format gets the same 5MB raw-upload budget; the per-format
  // experience is consistent ("upload up to 5MB").
  const UPLOAD_MAX = 5 * 1024 * 1024
  const BINARY_EXTENSIONS = new Set(['pdf', 'docx'])
  // `accept` only filters the native picker — drag-and-drop bypasses it.
  const ACCEPTED_EXTENSIONS = new Set(['txt', 'md', 'pdf', 'docx'])

  let {
    onsubmit,
    disabled = false,
    selectedTaskType = $bindable('summary' as TaskType),
    documentContent = $bindable(''),
    fileName = $bindable('')
  }: {
    onsubmit: (
      task: string,
      goal: string,
      documentContent: string,
      taskType: TaskType,
      expectedAnswer: string
    ) => void
    disabled?: boolean
    // Bindable : la page parente adapte titre/étapes au type de tâche choisi.
    selectedTaskType?: TaskType
    // Bindables : la page parente conserve le document d'une comparaison à
    // l'autre (« Nouvelle comparaison » ne force plus à le recharger).
    documentContent?: string
    fileName?: string
  } = $props()

  // Frontend-restricted subset of the backend's task_type Literal
  // (see backend/tool_arena/router.py::CompareRequest.task_type).
  // Phase 13 enables "qa" alongside "summary"; both run in sandbox mode
  // (document_content as ephemeral corpus). "extraction" stays hidden.
  // "knowledge_capture" routes to the interview loop instead of /compare:
  // the expert (the user) replaces the document as the invariant source.
  type TaskType = 'summary' | 'qa' | 'knowledge_capture'

  const taskTypes: { value: TaskType; label: string; prompt: string; goalText: string }[] = [
    {
      value: 'summary',
      label: m['toolArena.form.taskTypes.summary.label'](),
      prompt: m['toolArena.form.taskTypes.summary.prompt'](),
      goalText: m['toolArena.form.taskTypes.summary.goal']()
    },
    {
      value: 'qa',
      label: m['toolArena.form.taskTypes.qa.label'](),
      // Blank so the user types their actual question; the static
      // "Réponds à la question…" default used to be concatenated with the
      // prompt and shipped verbatim, so the engine answered the document's
      // title-line instead of the user's question.
      prompt: '',
      goalText: m['toolArena.form.taskTypes.qa.goal']()
    },
    {
      value: 'knowledge_capture',
      label: m['toolArena.form.taskTypes.knowledge_capture.label'](),
      prompt: '',
      goalText: m['toolArena.form.taskTypes.knowledge_capture.goal']()
    }
  ]

  const initial = taskTypes.find((t) => t.value === selectedTaskType) ?? taskTypes[0]
  let task = $state(initial.prompt)
  let goal = $state(initial.goalText)
  let fileError = $state('')
  let extracting = $state(false)
  // Each file pick gets a token; a slow extraction that finishes after the
  // user picked another file must not overwrite the newer one.
  let fileToken = 0
  // Optional ground-truth answer the user expects; rendered alongside the
  // blind A/B results so they can judge whether either engine found the
  // needle. Only shown for QA. Whitespace-only submissions are dropped at
  // the wire-format layer (see buildToolArenaRequest).
  let expectedAnswer = $state('')

  // QA in sandbox mode also requires document_content (backend validator
  // enforces non-empty doc for haystack='sandbox'). Benchmark mode (no doc,
  // canned eval_query) is a separate future toggle. knowledge_capture has no
  // document at all — the expert being interviewed IS the source.
  const requiresDocument = $derived(selectedTaskType !== 'knowledge_capture')
  const isCapture = $derived(selectedTaskType === 'knowledge_capture')
  const isQa = $derived(selectedTaskType === 'qa')

  // First unmet condition, shown under the button so a disabled button
  // always says why. null = ready to submit.
  const blocker = $derived.by(() => {
    if (disabled) return null
    if (requiresDocument && extracting) return m['toolArena.form.waitExtraction']()
    if (requiresDocument && !documentContent.trim()) return m['toolArena.form.needDocument']()
    if (!task.trim())
      return isCapture
        ? m['toolArena.form.needTopic']()
        : isQa
          ? m['toolArena.form.needQuestion']()
          : m['toolArena.form.needTask']()
    if (!goal.trim()) return m['toolArena.form.needTask']()
    return null
  })
  const canSubmit = $derived(!disabled && blocker === null)

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault()
    if (canSubmit) {
      onsubmit(
        task.trim(),
        goal.trim(),
        documentContent,
        selectedTaskType,
        expectedAnswer
      )
    }
  }

  function handleTaskTypeChange() {
    const selected = taskTypes.find(t => t.value === selectedTaskType)
    if (selected) {
      task = selected.prompt
      goal = selected.goalText
    }
  }

  function clearFile(error = '') {
    documentContent = ''
    fileName = ''
    fileError = error
  }

  async function handleFileChange(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    const token = ++fileToken
    fileError = ''
    extracting = false
    if (!file) {
      clearFile()
      return
    }
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    if (!ACCEPTED_EXTENSIONS.has(ext)) {
      clearFile(m['toolArena.form.fileUnsupported']())
      return
    }
    if (file.size > UPLOAD_MAX) {
      clearFile(m['toolArena.form.fileTooBig']())
      return
    }
    documentContent = ''
    fileName = file.name
    extracting = true
    let text = ''
    try {
      if (BINARY_EXTENSIONS.has(ext)) {
        const form = new FormData()
        form.append('file', file)
        const resp = await fetch(`${backendBase()}/tool-arena/documents/extract`, {
          method: 'POST',
          body: form
        })
        if (token !== fileToken) return
        if (!resp.ok) {
          clearFile(m['toolArena.form.extractFailed']({ status: String(resp.status) }))
          return
        }
        const body = (await resp.json()) as { document_content: string }
        text = body.document_content ?? ''
      } else {
        text = await file.text()
      }
    } catch {
      if (token === fileToken) clearFile(m['toolArena.form.readFailed']())
      return
    } finally {
      if (token === fileToken) extracting = false
    }
    if (token !== fileToken) return
    if (!text.trim()) {
      clearFile(m['toolArena.form.fileEmpty']())
      return
    }
    documentContent = text
  }

  const suggestions = [
    { icon: 'fr-icon-file-text-line', text: m['toolArena.form.suggestions.1.text']() },
    { icon: 'fr-icon-team-line', text: m['toolArena.form.suggestions.2.text']() },
    { icon: 'fr-icon-search-line', text: m['toolArena.form.suggestions.3.text']() },
    { icon: 'fr-icon-list-unordered', text: m['toolArena.form.suggestions.4.text']() }
  ]

  const qaSuggestions = [
    { icon: 'fr-icon-flag-line', text: m['toolArena.form.qaSuggestions.1.text']() },
    { icon: 'fr-icon-bar-chart-box-line', text: m['toolArena.form.qaSuggestions.2.text']() },
    { icon: 'fr-icon-team-line', text: m['toolArena.form.qaSuggestions.3.text']() },
    { icon: 'fr-icon-warning-line', text: m['toolArena.form.qaSuggestions.4.text']() }
  ]

  // En mode capture, les suggestions documentaires n'ont pas de sens — on
  // propose des exemples de sujets d'expertise (remplissent task uniquement).
  const captureSuggestions = [
    { icon: 'fr-icon-tools-line', text: m['toolArena.form.captureSuggestions.1.text']() },
    { icon: 'fr-icon-team-line', text: m['toolArena.form.captureSuggestions.2.text']() },
    { icon: 'fr-icon-discuss-line', text: m['toolArena.form.captureSuggestions.3.text']() },
    { icon: 'fr-icon-lightbulb-line', text: m['toolArena.form.captureSuggestions.4.text']() }
  ]

  // Suggestions only fill the task: the goal stays the one of the current
  // task type, so a suggestion can never contradict it.
  const activeSuggestions = $derived(isCapture ? captureSuggestions : isQa ? qaSuggestions : suggestions)
</script>

<form onsubmit={handleSubmit} class="gap-3 py-10 md:pb-12 md:pt-12 grid">
  <div class="fr-select-group">
    <label class="fr-label" for="tool-arena-task-type">
      {m['toolArena.form.taskType']()}
    </label>
    <select
      id="tool-arena-task-type"
      class="fr-select"
      bind:value={selectedTaskType}
      onchange={handleTaskTypeChange}
      {disabled}
    >
      {#each taskTypes as taskType (taskType.value)}
        <option value={taskType.value}>{taskType.label}</option>
      {/each}
    </select>
  </div>

  {#if requiresDocument}
    <div class="fr-upload-group" class:fr-upload-group--error={!!fileError}>
      <label class="fr-label" for="tool-arena-document">
        {m['toolArena.form.document']()}
        <span class="fr-hint-text">{m['toolArena.form.documentHint']()}</span>
      </label>
      <input
        id="tool-arena-document"
        data-testid="tool-arena-file-input"
        class="file-input-hidden"
        type="file"
        accept=".txt,.md,.pdf,.docx"
        onchange={handleFileChange}
        {disabled}
      />
      <label
        for="tool-arena-document"
        class="file-upload-btn"
        class:file-upload-btn--disabled={disabled}
        aria-disabled={disabled}
      >
        <span class="i-ri-upload-2-line" aria-hidden="true"></span>
        {fileName ? fileName : m['toolArena.form.chooseFile']()}
      </label>
      <div aria-live="polite">
        {#if fileError}
          <p class="fr-error-text">{fileError}</p>
        {:else if extracting}
          <p class="fr-info-text animate-pulse">{m['toolArena.form.extracting']({ name: fileName })}</p>
        {:else if fileName && documentContent}
          <p class="fr-valid-text">{m['toolArena.form.fileLoaded']({ name: fileName })}</p>
        {/if}
      </div>
    </div>
  {/if}

  <div class="mt-2">
    <p class="font-bold mb-3 fr-text--sm">{m['toolArena.form.suggestionsTitle']()}</p>
    <div class="gap-3 md:grid-cols-4 grid grid-cols-2">
      {#each activeSuggestions as suggestion (suggestion.text)}
        <button
          type="button"
          class="cg-border rounded-lg! bg-white p-3 text-left hover:bg-light-grey transition-colors cursor-pointer flex flex-col gap-2"
          onclick={(e) => {
            e.preventDefault()
            task = suggestion.text
          }}
          {disabled}
        >
          <span class={['text-primary text-lg', suggestion.icon]} aria-hidden="true"></span>
          <span class="fr-text--sm text-dark-grey mb-0!">{suggestion.text}</span>
        </button>
      {/each}
    </div>
  </div>

  <div class="fr-input-group">
    <label class="fr-label sr-only" for="tool-arena-task">{m['toolArena.form.taskLabel']()}</label>
    <textarea
      id="tool-arena-task"
      class="fr-input cg-border rounded-t-md! bg-white! rounded-b-none! border-solid!"
      rows="4"
      bind:value={task}
      placeholder={isQa
        ? m['toolArena.form.qaPlaceholder']()
        : isCapture
          ? m['toolArena.form.taskTypes.knowledge_capture.prompt']()
          : m['toolArena.form.taskPlaceholder']()}
      {disabled}
    ></textarea>
  </div>

  {#if isQa}
    <div class="fr-input-group">
      <label class="fr-label" for="tool-arena-expected-answer">
        {m['toolArena.form.expectedAnswer']()}
        <span class="fr-hint-text">{m['toolArena.form.expectedAnswerHint']()}</span>
      </label>
      <textarea
        id="tool-arena-expected-answer"
        data-testid="tool-arena-expected-answer"
        class="fr-input cg-border rounded-md! bg-white! border-solid!"
        rows="2"
        bind:value={expectedAnswer}
        placeholder={m['toolArena.form.expectedAnswerPlaceholder']()}
        {disabled}
      ></textarea>
    </div>
  {/if}

  <div class="gap-3 md:grid-flow-row-dense md:grid-cols-6 grid">
    <div class="fr-input-group md:col-span-4">
      <label class="fr-label sr-only" for="tool-arena-goal">{m['toolArena.form.goalLabel']()}</label>
      <input
        id="tool-arena-goal"
        data-testid="tool-arena-goal"
        type="text"
        class="fr-input cg-border rounded-md! bg-white! border-solid!"
        bind:value={goal}
        placeholder={m['toolArena.form.goalPlaceholder']()}
        {disabled}
      />
    </div>

    <div class="md:col-span-2 flex justify-end items-start">
      <Button
        type="submit"
        data-testid="tool-arena-submit"
        disabled={!canSubmit}
        aria-describedby="tool-arena-blocker"
      >
        {isCapture ? m['toolArena.form.submitCapture']() : m['toolArena.form.submit']()}
      </Button>
    </div>
  </div>
  <p
    id="tool-arena-blocker"
    data-testid="tool-arena-blocker"
    class="fr-text--sm text-grey text-right mb-0!"
    aria-live="polite"
  >
    {blocker ?? ''}
  </p>
</form>

<style lang="postcss">
  .fr-input {
    --border-plain-grey: var(--blue-france-main-525);
  }

  .file-input-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
  }

  .file-upload-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 10px 20px;
    background-color: #1f1f1f;
    color: #ffffff;
    font-size: 0.875rem;
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-radius: 0;
    cursor: pointer;
    transition: background-color 0.15s;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .file-upload-btn:hover {
    background-color: #fa520f;
  }

  .file-upload-btn--disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }

  /* A disabled submit must not look clickable (it turned orange on hover). */
  :global([data-testid='tool-arena-submit']:disabled),
  :global([data-testid='tool-arena-submit']:disabled:hover) {
    background-color: var(--background-disabled-grey) !important;
    color: var(--text-disabled-grey) !important;
    cursor: not-allowed;
  }
</style>
