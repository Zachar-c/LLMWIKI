// Browser regressions use synthetic data, a simulated model and a new SQLite file.
// Run after building the frontend: node backend/tests/web_ui_final_e2e.cjs <playwright module>
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
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'graduation-final-e2e-'))
  const port = await unusedPort()
  const base = `http://127.0.0.1:${port}`
  const database = path.join(temp, 'test.sqlite3')
  const python = process.env.GRAD_TEST_PYTHON || path.join(process.env.LOCALAPPDATA, 'Programs/Python/Python312/python.exe')
  const child = spawn(python, ['-m', 'backend.tests.web_ui_mock_server', String(port), database], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUTF8: '1', KNOWLEDGE_DB_PATH: database, PYTHONPATH: path.join(root, 'backend/.venv/Lib/site-packages') },
  })
  let logs = ''
  child.stdout.on('data', data => { logs += data })
  child.stderr.on('data', data => { logs += data })
  const report = { status: 'incomplete', model: 'simulated', database, port, checks: [] }
  let browser, page
  try {
    for (let i = 0; i < 120; i++) {
      if (child.exitCode !== null) throw new Error(`Server exited ${child.exitCode}: ${logs}`)
      try { if ((await fetch(`${base}/api/health`)).ok) break } catch {}
      if (i === 119) throw new Error(`Server readiness timeout: ${logs}`)
      await new Promise(resolve => setTimeout(resolve, 100))
    }
    browser = await chromium.launch({ channel: 'chrome', headless: true })
    page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    const api = async (endpoint, method = 'GET', body) => {
      const response = await fetch(`${base}${endpoint}`, {
        method, headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body),
      })
      assert(response.ok, `${method} ${endpoint} returned ${response.status}: ${await response.clone().text()}`)
      return response.json()
    }
    const guarded = () => page.evaluate(() => {
      const event = new Event('beforeunload', { cancelable: true })
      window.dispatchEvent(event)
      return event.defaultPrevented
    })
    const cancelReload = async selector => {
      const previous = await page.locator(selector).inputValue()
      const dialogPromise = page.waitForEvent('dialog', { timeout: 5000 })
      const reload = page.reload({ timeout: 5000 }).catch(() => null)
      const dialog = await dialogPromise
      assert.equal(dialog.type(), 'beforeunload')
      await dialog.dismiss()
      await reload
      assert.equal(await page.locator(selector).inputValue(), previous)
    }
    const switchView = name => page.getByRole('button', { name, exact: true }).click()

    await page.goto(base)
    await page.locator('#source-title').fill('自编登录回归资料')
    await page.locator('#source-origin').fill('本项目隔离自动测试')
    await page.locator('#source-content').fill('登录密码错误提示失败。连续失败五次暂停登录十分钟。')
    await cancelReload('#source-title')
    await switchView('Wiki')
    await switchView('资料库')
    assert.equal(await page.locator('#source-title').inputValue(), '自编登录回归资料')
    await page.locator('.brand').click()
    assert.equal(await page.locator('#source-title').inputValue(), '自编登录回归资料')
    report.checks.push('source draft survives tabs and brand, canceled refresh preserves input')
    await page.getByRole('button', { name: '保存到资料库' }).click()
    await page.getByRole('status').filter({ hasText: '已保存' }).waitFor()
    await page.locator('#source-title').waitFor({ state: 'visible' })
    assert.equal(await guarded(), false)
    report.checks.push('saved source clears leave warning')

    await switchView('Wiki')
    await page.locator('#wiki-topic').fill('登录密码')
    await page.locator('.wiki .source input').first().check()
    assert.equal(await guarded(), true)
    await page.getByRole('button', { name: '生成草稿', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '草稿已生成' }).waitFor()
    assert.equal(await guarded(), false)
    await page.locator('#wiki-title').fill('本地 Wiki 未保存')
    await cancelReload('#wiki-title')
    await page.locator('.brand').click()
    assert.equal(await guarded(), true)
    await switchView('Wiki')
    assert.equal(await page.locator('#wiki-title').inputValue(), '本地 Wiki 未保存')
    report.checks.push('wiki edit survives brand and canceled refresh, hidden draft remains protected')

    const wikiList = await api('/api/wiki-pages')
    const wiki = await api(`/api/wiki-pages/${wikiList[0].id}`)
    assert.equal(typeof wiki.content_hash, 'string')
    await api(`/api/wiki-pages/${wiki.id}`, 'PUT', { title: '另一窗口 Wiki 已保存', sections: wiki.sections, base_hash: wiki.content_hash })
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '其他页面' }).waitFor()
    assert.equal(await page.locator('#wiki-title').inputValue(), '本地 Wiki 未保存')
    page.once('dialog', dialog => dialog.accept())
    await page.locator('.wiki .page-button').first().click()
    await page.locator('#wiki-title').waitFor({ state: 'visible' })
    await page.waitForFunction(() => document.querySelector('#wiki-title').value === '另一窗口 Wiki 已保存')
    await page.locator('#wiki-title').fill('重新加载后人工修改')
    await page.getByRole('button', { name: '保存草稿', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '草稿已保存' }).waitFor()
    assert.equal(await guarded(), false)
    report.checks.push('wiki conflict preserves local edit and reload enables a new save')

    const reviewedWiki = await api(`/api/wiki-pages/${wiki.id}`)
    await api(`/api/wiki-pages/${wiki.id}`, 'PUT', { title: '其他页面保存的待审核 Wiki', sections: reviewedWiki.sections, base_hash: reviewedWiki.content_hash })
    await page.getByRole('button', { name: '确认原文并发布', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '其他页面' }).waitFor()
    assert.equal(await page.locator('#wiki-title').inputValue(), '重新加载后人工修改')
    assert.equal((await api(`/api/wiki-pages/${wiki.id}`)).status, 'draft')
    report.checks.push('stale wiki publish receives conflict and leaves the latest content in draft')

    const pageCount = (await api('/api/wiki-pages')).length
    await page.context().setOffline(true)
    await page.getByRole('button', { name: '生成草稿', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '无法连接服务' }).waitFor()
    assert.equal(await page.locator('#wiki-topic').inputValue(), '登录密码')
    assert.equal(await page.getByRole('button', { name: '生成草稿', exact: true }).isEnabled(), true)
    await page.context().setOffline(false)
    assert.equal((await api('/api/wiki-pages')).length, pageCount)
    report.checks.push('offline wiki request restores controls and preserves inputs without saving a draft')

    await page.route('**/api/wiki-drafts', route => route.fulfill({
      status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '当前模型额度或请求频率受限，请稍后重试。' }),
    }))
    await page.getByRole('button', { name: '生成草稿', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '当前模型额度或请求频率受限' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '生成草稿', exact: true }).isEnabled(), true)
    await page.unroute('**/api/wiki-drafts')
    report.checks.push('model 503 reaches wiki error state and restores controls')

    await switchView('用例生成')
    await page.locator('#case-requirement').fill('登录密码错误边界测试')
    await page.locator('.cases-source input').first().check()
    assert.equal(await guarded(), true)
    await page.getByRole('button', { name: '生成用例', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '已生成用例草稿' }).waitFor()
    assert.equal(await guarded(), false)
    await page.locator('#case-title-0').fill('本地用例未保存')
    await cancelReload('#case-title-0')
    await page.locator('.brand').click()
    assert.equal(await guarded(), true)
    await switchView('用例生成')
    await page.locator('#case-title-0').waitFor({ state: 'visible' })
    assert.equal(await page.locator('#case-title-0').inputValue(), '本地用例未保存')
    report.checks.push('case edit survives brand and canceled refresh, hidden draft remains protected')

    const batches = await api('/api/case-batches')
    const batch = await api(`/api/case-batches/${batches[0].id}`)
    assert.equal(typeof batch.content_hash, 'string')
    const externalCases = batch.cases.map(item => ({ ...item, title: '另一窗口用例已保存' }))
    await api(`/api/case-batches/${batch.id}`, 'PUT', { cases: externalCases, confirmed: true, base_hash: batch.content_hash })
    await page.locator('.cases-confirm input').check()
    await page.getByRole('button', { name: '确认并保存', exact: true }).click()
    await page.getByRole('alert').filter({ hasText: '其他页面' }).waitFor()
    assert.equal(await page.locator('#case-title-0').inputValue(), '本地用例未保存')
    page.once('dialog', dialog => dialog.accept())
    await page.locator('.cases-history-item').first().click()
    await page.waitForFunction(() => document.querySelector('#case-title-0').value === '另一窗口用例已保存')
    await page.locator('#case-title-0').fill('重新核对后保存用例')
    await page.locator('.cases-confirm input').check()
    await page.getByRole('button', { name: '确认并保存', exact: true }).click()
    await page.getByRole('status').filter({ hasText: '已保存人工核对' }).waitFor()
    assert.equal(await guarded(), false)
    report.checks.push('case conflict preserves local edit and reload enables a new confirmed save')

    let releaseReview
    const reviewGate = new Promise(resolve => { releaseReview = resolve })
    let intercepted
    const requestIntercepted = new Promise(resolve => { intercepted = resolve })
    await page.route('**/api/case-batches/*/review', async route => {
      intercepted()
      await reviewGate
      await route.continue()
    })
    await page.getByRole('button', { name: 'AI 审查', exact: true }).click()
    await requestIntercepted
    assert.equal(await guarded(), true)
    assert.equal(await page.locator('#case-title-0').isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: 'AI 审查', exact: true }).isDisabled(), true)
    await cancelReload('#case-title-0')
    releaseReview()
    await page.getByRole('status').filter({ hasText: '审查已完成' }).waitFor()
    assert.equal(await guarded(), false)
    await page.unroute('**/api/case-batches/*/review')
    report.checks.push('busy review prevents duplicate actions and guards refresh, completion clears guard')
    assert.deepEqual(errors, [])
    report.pageErrors = errors
    report.screenshot = path.join(temp, 'screen.png')
    await page.screenshot({ path: report.screenshot, fullPage: true })
    report.status = 'passed'
  } catch (error) {
    report.error = String(error.stack || error)
    process.exitCode = 1
  } finally {
    if (browser) await browser.close()
    child.kill()
    report.result = path.join(temp, 'result.json')
    fs.writeFileSync(report.result, JSON.stringify(report, null, 2), { flag: 'wx' })
    console.log(JSON.stringify(report))
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1 })
