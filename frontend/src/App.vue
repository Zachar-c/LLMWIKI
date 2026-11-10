<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import WikiView from './WikiView.vue'
import CasesView from './CasesView.vue'

const view = ref('sources')
const visited = reactive({ wiki: false, cases: false })
function showView(name) {
  view.value = name
  if (name !== 'sources') visited[name] = true
}

const sources = ref([])
const selected = ref(null)
const listLoading = ref(false)
const detailLoading = ref(false)
const listError = ref('')
const detailError = ref('')
const formError = ref('')
const savedMessage = ref('')
const saving = ref(false)
const readingFile = ref(false)
const fileKey = ref(0)
const readerTab = ref('original')
const openChunk = ref(null)
const form = reactive({ title: '', origin: '', version: '', content: '' })
const charCount = computed(() => [...form.content].length)
let detailRequest = 0
let listRequest = 0

async function apiJson(url, options) {
  let response
  try {
    response = await fetch(url, options)
  } catch {
    throw new Error('未能连接服务。若刚刚点过保存，请先刷新资料列表核对，避免重复导入。')
  }
  if (response.status === 422) {
    const data = await response.json()
    const field = { title: '标题', origin: '来源', version: '版本', content: '正文' }[data.detail[0].loc.at(-1)] || '输入'
    throw new Error(`${field}不符合要求，请检查是否为空或超过长度限制。`)
  }
  if (response.status === 404) throw new Error('资料不存在，请刷新列表。')
  if (!response.ok) throw new Error(`请求未完成（HTTP ${response.status}）。请先刷新列表核对，再尝试操作。`)
  return response.json()
}

async function loadSources() {
  const request = ++listRequest
  listLoading.value = true
  listError.value = ''
  try {
    const result = await apiJson('/api/sources')
    if (request === listRequest) sources.value = result
  } catch (error) {
    if (request === listRequest) listError.value = error.message
  } finally {
    if (request === listRequest) listLoading.value = false
  }
}

async function selectSource(id) {
  const request = ++detailRequest
  selected.value = null
  detailLoading.value = true
  detailError.value = ''
  readerTab.value = 'original'
  openChunk.value = null
  try {
    const result = await apiJson(`/api/sources/${id}`)
    if (request === detailRequest) selected.value = result
  } catch (error) {
    if (request === detailRequest) detailError.value = error.message
  } finally {
    if (request === detailRequest) detailLoading.value = false
  }
}

async function readFile(event) {
  const file = event.target.files[0]
  if (!file) return
  formError.value = ''
  savedMessage.value = ''
  if (!/\.(txt|md)$/i.test(file.name)) {
    formError.value = '请选择 .txt 或 .md 文件。'
    return
  }
  if (file.size > 400_000) {
    formError.value = '文件不能超过 400 KB；可以选择其中一个主题导入。'
    return
  }
  readingFile.value = true
  try {
    const bytes = await file.arrayBuffer()
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes)
    if ([...text].length > 100_000) {
      formError.value = '正文不能超过 100000 个字符。'
      return
    }
    form.content = text
    if (!form.title.trim()) form.title = file.name.replace(/\.(txt|md)$/i, '').slice(0, 200)
  } catch {
    formError.value = '无法读取 UTF-8 文本，请将文件另存为 UTF-8 后再导入。'
  } finally {
    readingFile.value = false
  }
}

async function saveSource() {
  formError.value = ''
  savedMessage.value = ''
  if (!form.title.trim() || !form.content.trim()) {
    formError.value = '请填写标题和非空正文。'
    return
  }
  if (charCount.value > 100_000) {
    formError.value = '正文不能超过 100000 个字符。'
    return
  }
  saving.value = true
  try {
    const result = await apiJson('/api/sources', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    ++detailRequest
    selected.value = result
    detailLoading.value = false
    detailError.value = ''
    readerTab.value = 'original'
    openChunk.value = null
    savedMessage.value = `已保存《${result.title}》，原文和 ${result.chunk_count} 个片段可在左侧查看。`
    Object.assign(form, { title: '', origin: '', version: '', content: '' })
    fileKey.value += 1
    await loadSources()
  } catch (error) {
    formError.value = error.message
  } finally {
    saving.value = false
  }
}

onMounted(loadSources)
</script>

<template>
  <header class="app-header">
    <a class="brand" href="/" aria-label="测试知识库首页">
      <span class="brand-mark" aria-hidden="true">知</span>
      <span>测试知识库<small>TESTING KNOWLEDGE</small></span>
    </a>
    <nav class="main-nav" aria-label="功能导航">
      <button :class="{ 'nav-active': view === 'sources' }" type="button" @click="showView('sources')">资料库</button>
      <button :class="{ 'nav-active': view === 'wiki' }" type="button" @click="showView('wiki')">Wiki</button>
      <button :class="{ 'nav-active': view === 'cases' }" type="button" @click="showView('cases')">用例生成</button>
    </nav>
    <span class="local-label"><i aria-hidden="true"></i>本机资料</span>
  </header>

  <main v-show="view === 'sources'">
    <div class="page-heading">
      <div><p class="eyebrow">01 / 资料管理</p><h1>从原始资料开始</h1><p>保留来源与版本，让整理后的知识始终有据可查。</p></div>
      <p class="scope-note">当前支持 TXT / Markdown<br />每份最多 100000 字符</p>
    </div>

    <div class="workspace">
      <aside class="source-list panel" aria-labelledby="list-title">
        <div class="panel-heading"><h2 id="list-title">我的资料 <span class="count">{{ sources.length }}</span></h2><button type="button" class="text-button" :disabled="listLoading" @click="loadSources">{{ listLoading ? '读取中' : '刷新' }}</button></div>
        <p v-if="listError" class="error-message" role="alert">{{ listError }}</p>
        <p v-if="!listLoading && !listError && !sources.length" class="empty-list">还没有资料。<br />从右侧导入第一份文本。</p>
        <ul>
          <li v-for="source in sources" :key="source.id">
            <button type="button" class="source-item" :class="{ selected: selected?.id === source.id }" :aria-pressed="selected?.id === source.id" @click="selectSource(source.id)">
              <span class="document-icon" aria-hidden="true">文</span>
              <span class="source-item-text"><strong>{{ source.title }}</strong><span>{{ source.version || '未标注版本' }} · {{ source.char_count }} 字符</span></span>
            </button>
          </li>
        </ul>
      </aside>

      <section class="reader panel" aria-label="资料阅读区" :aria-busy="detailLoading">
        <p v-if="detailLoading" class="reader-state" role="status">正在读取原文…</p>
        <p v-else-if="detailError" class="error-message" role="alert">{{ detailError }}</p>
        <template v-else-if="selected">
          <div class="reader-heading"><p class="eyebrow">原始资料 / #{{ selected.id }}</p><h2>{{ selected.title }}</h2><dl class="source-meta"><div><dt>版本</dt><dd>{{ selected.version || '未标注' }}</dd></div><div><dt>来源</dt><dd>{{ selected.origin || '未填写' }}</dd></div><div><dt>内容</dt><dd>{{ selected.char_count }} 字符 · {{ selected.chunk_count }} 片段</dd></div></dl></div>
          <div class="reader-tabs" role="group" aria-label="查看内容">
            <button type="button" :aria-pressed="readerTab === 'original'" @click="readerTab = 'original'">完整原文</button>
            <button type="button" :aria-pressed="readerTab === 'chunks'" @click="readerTab = 'chunks'">原文片段 <span>{{ selected.chunk_count }}</span></button>
          </div>
          <div class="reading-body">
            <pre v-if="readerTab === 'original'" class="original-text">{{ selected.content }}</pre>
            <div v-else class="chunk-list">
              <p class="help">片段保留原文，相邻片段存在重叠，供后续检索引用。</p>
              <div v-for="chunk in selected.chunks" :key="chunk.id" class="chunk">
                <button type="button" :aria-expanded="openChunk === chunk.id" :aria-controls="`chunk-${chunk.id}`" @click="openChunk = openChunk === chunk.id ? null : chunk.id"><strong>片段 {{ chunk.ordinal }}</strong><span>原文第 {{ chunk.start_offset + 1 }}–{{ chunk.end_offset }} 字符</span><span aria-hidden="true">{{ openChunk === chunk.id ? '−' : '+' }}</span></button>
                <pre v-if="openChunk === chunk.id" :id="`chunk-${chunk.id}`" class="original-text chunk-text">{{ chunk.text }}</pre>
              </div>
            </div>
          </div>
          <details class="fingerprint"><summary>内容校验值 · SHA-256</summary><code>{{ selected.sha256 }}</code><p>用于核对接收到的文本；相同内容也可以作为不同版本保存。</p></details>
        </template>
        <div v-else class="reader-empty">
          <span class="empty-mark" aria-hidden="true">原</span><p class="eyebrow">保留原文，才能核对知识</p><h2>选一份资料，开始阅读</h2><p>导入后可查看完整原文和片段。<br />Wiki 整理和用例生成将使用这些来源。</p>
          <ol><li><span>1</span>导入公开或自编文本</li><li><span>2</span>补充来源与版本</li><li><span>3</span>查看保存的原文</li></ol>
        </div>
      </section>

      <aside class="import-panel panel" aria-labelledby="import-title">
        <div class="panel-heading"><h2 id="import-title">导入资料</h2><span class="small-label">新建原文</span></div>
        <form @submit.prevent="saveSource">
          <fieldset :disabled="saving || readingFile">
            <label for="source-file" class="field-label">从文件读取</label>
            <input id="source-file" :key="fileKey" type="file" accept=".txt,.md" aria-describedby="file-help" @change="readFile" />
            <p id="file-help" class="help">UTF-8 文本，最大 400 KB；也可以在下方粘贴。</p>
            <label for="source-title" class="field-label">标题 <span>必填</span></label><input id="source-title" v-model="form.title" type="text" maxlength="200" required placeholder="例如：登录测试实践笔记" />
            <label for="source-origin" class="field-label">来源</label><input id="source-origin" v-model="form.origin" type="text" maxlength="1000" placeholder="公开原文链接，或注明自编" />
            <label for="source-version" class="field-label">资料版本</label><input id="source-version" v-model="form.version" type="text" maxlength="100" placeholder="例如：v1 / 对应文档版本" />
            <div class="field-label"><label for="source-content">正文 <span>必填</span></label><span :class="{ 'over-limit': charCount > 100000 }">{{ charCount }} / 100000</span></div>
            <textarea id="source-content" v-model="form.content" rows="9" required placeholder="粘贴公开资料或自编文本，保留原始内容…"></textarea>
            <p class="help">保存后保留此份原文。更新资料时，请作为新版本导入。</p>
            <button class="primary-button" type="submit">{{ saving ? '正在保存…' : readingFile ? '读取文件中…' : '保存到资料库' }}<span aria-hidden="true">↗</span></button>
          </fieldset>
          <p v-if="formError" class="error-message" role="alert">{{ formError }}</p>
          <p v-if="savedMessage" class="success-message" role="status">{{ savedMessage }}</p>
        </form>
        <p class="data-note">请使用公开或自编资料，勿导入公司内部数据。</p>
      </aside>
    </div>
    <footer>资料库 · 原文为后续知识整理和测试用例生成提供依据。</footer>
  </main>
  <main v-show="view !== 'sources'">
    <WikiView v-if="visited.wiki" v-show="view === 'wiki'" :active="view === 'wiki'" />
    <CasesView v-if="visited.cases" v-show="view === 'cases'" :active="view === 'cases'" />
  </main>
</template>
