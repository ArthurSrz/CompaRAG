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

  const TEXT_MAX = 500 * 1024
  const BINARY_MAX = 5 * 1024 * 1024
  const BINARY_EXTENSIONS = new Set(['pdf', 'docx'])

  let {
    onsubmit,
    disabled = false
  }: {
    onsubmit: (task: string, goal: string, documentContent: string, taskType: TaskType) => void
    disabled?: boolean
  } = $props()

  // 1-1 with backend Literal["summary","qa","extraction"] in
  // backend/tool_arena/router.py::CompareRequest.task_type
  type TaskType = 'summary' | 'qa' | 'extraction'

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
      prompt: m['toolArena.form.taskTypes.qa.prompt'](),
      goalText: m['toolArena.form.taskTypes.qa.goal']()
    },
    {
      value: 'extraction',
      label: m['toolArena.form.taskTypes.extraction.label'](),
      prompt: m['toolArena.form.taskTypes.extraction.prompt'](),
      goalText: m['toolArena.form.taskTypes.extraction.goal']()
    }
  ]

  let selectedTaskType = $state<TaskType>(taskTypes[0].value)
  let task = $state(taskTypes[0].prompt)
  let goal = $state(taskTypes[0].goalText)
  let documentContent = $state('')
  let fileName = $state('')
  let fileError = $state('')

  // Summary and extraction operate on a user-provided document; QA can run
  // against the static corpus, so it doesn't require an upload.
  const requiresDocument = $derived(selectedTaskType !== 'qa')

  const canSubmit = $derived(
    task.trim().length > 0 &&
    goal.trim().length > 0 &&
    (!requiresDocument || documentContent.trim().length > 0) &&
    !disabled
  )

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault()
    if (canSubmit) {
      onsubmit(task.trim(), goal.trim(), documentContent, selectedTaskType)
    }
  }

  function handleTaskTypeChange() {
    const selected = taskTypes.find(t => t.value === selectedTaskType)
    if (selected) {
      task = selected.prompt
      goal = selected.goalText
    }
  }

  async function handleFileChange(e: Event) {
    const input = e.target as HTMLInputElement
    const file = input.files?.[0]
    fileError = ''
    if (!file) {
      documentContent = ''
      fileName = ''
      return
    }
    const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
    const isBinary = BINARY_EXTENSIONS.has(ext)
    const limit = isBinary ? BINARY_MAX : TEXT_MAX
    if (file.size > limit) {
      const human = isBinary ? '5 Mo' : '500 Ko'
      fileError = `Le fichier est trop volumineux (max ${human}).`
      documentContent = ''
      fileName = ''
      return
    }
    fileName = file.name
    if (isBinary) {
      try {
        const form = new FormData()
        form.append('file', file)
        const resp = await fetch(`${backendBase()}/tool-arena/documents/extract`, {
          method: 'POST',
          body: form
        })
        if (!resp.ok) {
          fileError = `Échec de l'extraction (${resp.status}).`
          documentContent = ''
          fileName = ''
          return
        }
        const body = (await resp.json()) as { document_content: string }
        documentContent = body.document_content ?? ''
      } catch {
        fileError = 'Impossible de lire le fichier.'
        documentContent = ''
        fileName = ''
      }
      return
    }
    const reader = new FileReader()
    reader.onload = (ev) => {
      documentContent = (ev.target?.result as string) ?? ''
    }
    reader.onerror = () => {
      fileError = 'Impossible de lire le fichier.'
      documentContent = ''
    }
    reader.readAsText(file)
  }

  const suggestions = [
    { icon: 'fr-icon-file-text-line', text: m['toolArena.form.suggestions.1.text']() },
    { icon: 'fr-icon-bar-chart-box-line', text: m['toolArena.form.suggestions.2.text']() },
    { icon: 'fr-icon-search-line', text: m['toolArena.form.suggestions.3.text']() },
    { icon: 'fr-icon-question-line', text: m['toolArena.form.suggestions.4.text']() }
  ]
</script>

<form onsubmit={handleSubmit} class="gap-3 py-10 md:pb-12 md:pt-12 grid">
  <div class="fr-select-group">
    <label class="fr-label" for="tool-arena-task-type">
      Type de tâche
    </label>
    <select
      id="tool-arena-task-type"
      class="fr-select"
      bind:value={selectedTaskType}
      onchange={handleTaskTypeChange}
      {disabled}
    >
      {#each taskTypes as taskType}
        <option value={taskType.value}>{taskType.label}</option>
      {/each}
    </select>
  </div>

  {#if requiresDocument}
    <div class="fr-upload-group" class:fr-upload-group--error={!!fileError}>
      <label class="fr-label" for="tool-arena-document">
        Document à analyser
        <span class="fr-hint-text">Formats acceptés : .txt, .md (500 Ko max), .pdf, .docx (5 Mo max)</span>
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
        {fileName ? fileName : 'Choisir un fichier'}
      </label>
      {#if fileError}
        <p class="fr-error-text">{fileError}</p>
      {/if}
      {#if fileName && !fileError}
        <p class="fr-valid-text">{fileName} chargé avec succès</p>
      {/if}
    </div>
  {/if}

  <div class="fr-input-group">
    <label class="fr-label hidden!" for="tool-arena-task">Task</label>
    <textarea
      id="tool-arena-task"
      class="fr-input cg-border rounded-t-md! bg-white! rounded-b-none! border-solid!"
      rows="4"
      bind:value={task}
      placeholder={m['toolArena.form.taskPlaceholder']()}
      {disabled}
    ></textarea>
  </div>

  <div class="gap-3 md:grid-flow-row-dense md:grid-cols-6 grid">
    <div class="fr-input-group md:col-span-4">
      <label class="fr-label hidden!" for="tool-arena-goal">Goal</label>
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
      <Button type="submit" data-testid="tool-arena-submit" disabled={!canSubmit}>
        {m['toolArena.form.submit']()}
      </Button>
    </div>
  </div>
</form>

<div class="mt-2">
  <p class="font-bold mb-4">Suggestions</p>
  <div class="gap-4 md:grid-cols-4 grid grid-cols-2">
    {#each suggestions as suggestion}
      <button
        type="button"
        class="cg-border rounded-lg! bg-white p-4 text-left hover:bg-light-grey transition-colors cursor-pointer flex flex-col gap-3"
        onclick={(e) => {
          e.preventDefault()
          task = suggestion.text
          goal = m['toolArena.form.taskTypes.summarize.goal']()
        }}
      >
        <span class={['text-primary text-xl', suggestion.icon]} aria-hidden="true"></span>
        <span class="fr-text--sm text-dark-grey">{suggestion.text}</span>
      </button>
    {/each}
  </div>
</div>

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
</style>
