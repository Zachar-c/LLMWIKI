// Real OpenCode browser acceptance, synthetic data and isolated SQLite only.
// Run: node backend/tests/web_ui_real_e2e.cjs <absolute playwright module path>
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const net = require('node:net')
const { spawn } = require('node:child_process')
const { chromium } = require(process.argv[2])
const root = path.resolve(__dirname, '../..')

async function unusedPort() {
  const socket = net.createServer()
  await new Promise((resolve, reject) => socket.once('error', reject).listen(0, '127.0.0.1', resolve))
  const port = socket.address().port
  await new Promise(resolve => socket.close(resolve))
  return port
}

async function main() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'graduation-real-e2e-'))
  const port = await unusedPort()
  const base = `http://127.0.0.1:${port}`
  const python = process.env.GRAD_TEST_PYTHON || path.join(process.env.LOCALAPPDATA, 'Programs/Python/Python312/python.exe')
  const env = { ...process.env, PYTHONUTF8: '1', PYTHONPATH: path.join(root, 'backend/.venv/Lib/site-packages'), KNOWLEDGE_DB_PATH: path.join(temp, 'test.sqlite3') }
  // A temporary test override does not change the application's default model.
  env.GRADUATION_OPENCODE_MODEL = process.env.GRAD_TEST_MODEL || 'opencode/deepseek-v4.1-flash-free'
  const chatgpt = process.env.GRAD_TEST_PROVIDER === 'chatgpt'
  if (chatgpt) env.GRADUATION_CHATGPT_MODEL = process.env.GRAD_TEST_MODEL || 'gpt-6-luna'
  const entry = chatgpt ? 'backend.app.web_chatgpt:app' : 'backend.app.web_opencode_fixed:app'
  const child = spawn(python, ['-m', 'uvicorn', entry, '--host', '127.0.0.1', '--port', String(port)], { cwd: root, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let logs = ''
  child.stdout.on('data', data => { logs += data })
  child.stderr.on('data', data => { logs += data })
  const report = { provider: chatgpt ? 'ChatGPT subscription / Codex CLI' : 'OpenCode', model: chatgpt ? env.GRADUATION_CHATGPT_MODEL : env.GRADUATION_OPENCODE_MODEL, simulated: false, status: 'incomplete', step: 'start', database: env.KNOWLEDGE_DB_PATH, port }
  let browser, page
  try {
    for (let i = 0; i < 120; i++) {
      if (child.exitCode !== null) throw new Error(`server exited ${child.exitCode}: ${logs}`)
      try { if ((await fetch(`${base}/api/health`)).ok) break } catch {}
      if (i === 119) throw new Error('server readiness timeout')
      await new Promise(resolve => setTimeout(resolve, 150))
    }
    browser = await chromium.launch({ channel: 'chrome', headless: true })
    page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const requestModel = async (pattern, trigger) => {
      // Backend itself allows 240 seconds; allow extra time for it to return
      // a timeout response instead of racing the browser's own deadline.
      const pending = page.waitForResponse(response => response.url().includes(pattern) && response.request().method() === 'POST', { timeout: 270000 })
      await trigger()
      const response = await pending
      const body = await response.json()
      if (!response.ok()) throw new Error(`HTTP ${response.status()}: ${body.detail || '模型调用失败'}`)
      return body
    }

    report.step = 'import_synthetic_source'
    await page.goto(base)
    await page.locator('#source-title').fill('自编示例：书店登录测试')
    await page.locator('#source-origin').fill('本项目自编演示，不含公司资料')
    await page.locator('#source-version').fill('demo-v1')
    await page.locator('#source-content').fill('示例书店登录：账号与密码均为必填。正确账号密码进入个人书架并显示昵称。密码错误提示账号或密码不正确。连续错误五次暂停登录十分钟，暂停期间正确密码也不能登录。')
    await page.getByRole('button', { name: '保存到资料库' }).click()
    await page.getByRole('status').filter({ hasText: '已保存' }).waitFor()

    report.step = 'generate_wiki'
    await page.getByRole('button', { name: 'Wiki', exact: true }).click()
    await page.locator('#wiki-topic').fill('登录测试规则')
    await page.locator('.wiki .source input').first().check()
    const wiki = await requestModel('/api/wiki-drafts', () => page.getByRole('button', { name: '生成草稿' }).click())
    assert.equal(wiki.status, 'draft')
    assert.ok(wiki.sections.length > 0 && wiki.evidence.length > 0)
    await page.getByRole('status').filter({ hasText: '草稿已生成' }).waitFor()
    await page.locator('.wiki details summary').first().click()
    assert((await page.locator('.wiki details').first().innerText()).includes('账号与密码均为必填'))
    report.wiki_id = wiki.id

    report.step = 'publish_wiki'
    await page.getByRole('button', { name: '确认原文并发布' }).click()
    await page.getByRole('status').filter({ hasText: '已发布' }).waitFor()

    report.step = 'generate_cases'
    await page.getByRole('button', { name: '用例生成' }).click()
    await page.locator('#case-requirement').fill('登录密码必填、正确登录、密码错误和连续失败限制测试')
    await page.locator('.cases-source input').first().check()
    const batch = await requestModel('/api/case-batches/generate', () => page.getByRole('button', { name: '生成用例' }).click())
    assert.ok(batch.cases.length > 0 && batch.evidence.length > 0)
    report.batch_id = batch.id
    report.case_count = batch.cases.length
    await page.getByRole('status').filter({ hasText: '已生成用例草稿' }).waitFor()
    await page.getByRole('button', { name: '导出 CSV' }).click()
    await page.getByRole('alert').filter({ hasText: '请先人工核对' }).waitFor()

    report.step = 'review_cases'
    const reviewed = await requestModel(`/api/case-batches/${batch.id}/review`, () => page.getByRole('button', { name: 'AI 审查' }).click())
    assert.ok(Array.isArray(reviewed.review.issues))
    report.review_count = reviewed.review.issues.length
    await page.getByRole('status').filter({ hasText: '审查已完成' }).waitFor()

    report.step = 'confirm_and_export_isolated_test_data'
    await page.locator('.cases-confirm input').check()
    await page.getByRole('button', { name: '确认并保存' }).click()
    await page.getByRole('status').filter({ hasText: '已保存人工核对' }).waitFor()
    const pendingDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出 CSV' }).click()
    const download = await pendingDownload
    report.csv = path.join(temp, 'cases.csv')
    await download.saveAs(report.csv)
    assert.ok(fs.statSync(report.csv).size > 0)
    assert.deepEqual(errors, [])
    report.status = 'passed'
    report.step = 'finished'
  } catch (error) {
    report.error = String(error.message || error)
    if (page) {
      try {
        await page.getByRole('alert').first().waitFor({ timeout: 3000 })
      } catch {}
    }
    try {
      report.wiki_count = (await (await fetch(`${base}/api/wiki-pages`)).json()).length
      report.case_batch_count = (await (await fetch(`${base}/api/case-batches`)).json()).length
    } catch {}
    process.exitCode = 1
  } finally {
    if (page) {
      try { report.screenshot = path.join(temp, 'screen.png'); await page.screenshot({ path: report.screenshot, fullPage: true }) } catch {}
    }
    if (browser) await browser.close()
    child.kill()
    const resultPath = path.join(temp, 'result.json')
    fs.writeFileSync(resultPath, JSON.stringify(report, null, 2), { flag: 'wx' })
    console.log(JSON.stringify({ ...report, result: resultPath }))
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1 })
