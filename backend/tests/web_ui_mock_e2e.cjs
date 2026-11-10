// Isolated browser integration: simulated model, synthetic data, temporary SQLite.
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const net = require('node:net')
const { spawn } = require('node:child_process')
const { chromium } = require(process.argv[2])
const root = path.resolve(__dirname, '../..')

async function unusedPort() {
  const server = net.createServer()
  await new Promise((resolve, reject) => server.once('error', reject).listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

async function main() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'graduation-web-e2e-'))
  const port = await unusedPort()
  const base = `http://127.0.0.1:${port}`
  const python = process.env.GRAD_TEST_PYTHON || path.join(root, 'backend/.venv/Scripts/python.exe')
  const pythonPath = path.join(root, 'backend/.venv/Lib/site-packages')
  const child = spawn(python, ['-m', 'backend.tests.web_ui_mock_server', String(port), path.join(temp, 'test.sqlite3')], { cwd: root, env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: pythonPath }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  let logs = ''
  child.stdout.on('data', data => { logs += data })
  child.stderr.on('data', data => { logs += data })
  let browser
  try {
    for (let i = 0; i < 120; i++) {
      if (child.exitCode !== null) throw new Error(`server exited: ${child.exitCode}: ${logs}`)
      try { if ((await fetch(`${base}/api/health`)).ok) break } catch {}
      if (i === 119) throw new Error(`server readiness timeout: ${logs}`)
      await new Promise(resolve => setTimeout(resolve, 150))
    }
    browser = await chromium.launch({ channel: 'chrome', headless: true })
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
    const errors = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto(base)
    await page.locator('#source-title').fill('自编登录规则')
    await page.locator('#source-origin').fill('本地测试自编资料')
    await page.locator('#source-version').fill('demo-v1')
    await page.locator('#source-content').fill('登录密码错误提示失败。连续失败五次暂停登录十分钟。')
    await page.getByRole('button', { name: '保存到资料库' }).click()
    await page.getByRole('status').filter({ hasText: '已保存' }).waitFor()
    await page.getByRole('button', { name: 'Wiki', exact: true }).click()
    await page.locator('#wiki-topic').fill('登录密码')
    await page.locator('.wiki .source input').first().check()
    await page.getByRole('button', { name: '生成草稿' }).click()
    await page.getByRole('status').filter({ hasText: '草稿已生成' }).waitFor()
    await page.locator('.wiki details summary').first().click()
    assert((await page.locator('.wiki details').first().innerText()).includes('登录密码错误提示失败'))
    await page.getByRole('button', { name: '确认原文并发布' }).click()
    await page.getByRole('status').filter({ hasText: '已发布' }).waitFor()
    await page.getByRole('button', { name: '用例生成' }).click()
    await page.locator('#case-requirement').fill('登录密码错误测试')
    await page.locator('.cases-source input').first().check()
    await page.getByRole('button', { name: '生成用例' }).click()
    await page.getByRole('status').filter({ hasText: '已生成用例草稿' }).waitFor()
    await page.getByRole('button', { name: '导出 CSV' }).click()
    await page.getByRole('alert').filter({ hasText: '请先人工核对' }).waitFor()
    await page.getByRole('button', { name: 'AI 审查' }).click()
    await page.getByRole('status').filter({ hasText: '审查已完成' }).waitFor()
    await page.getByText('模拟审查：补充失败边界').waitFor()
    await page.locator('#case-title-0').fill('人工核对：密码错误')
    await page.locator('.cases-confirm input').check()
    await page.getByRole('button', { name: '确认并保存' }).click()
    await page.getByRole('status').filter({ hasText: '已保存人工核对' }).waitFor()
    await page.getByText('用例已修改，已有审查结果可能过期。').waitFor()
    const pendingDownload = page.waitForEvent('download')
    await page.getByRole('button', { name: '导出 CSV' }).click()
    const download = await pendingDownload
    const output = path.join(temp, 'cases.csv')
    await download.saveAs(output)
    assert(fs.readFileSync(output, 'utf8').includes('人工核对：密码错误'))
    assert.deepEqual(errors, [])
    const screen = path.join(temp, 'screen.png')
    await page.screenshot({ path: screen, fullPage: true })
    console.log(JSON.stringify({ status: 'passed', model: 'simulated', database: path.join(temp, 'test.sqlite3'), csv: output, screenshot: screen, port, pageErrors: errors }))
  } finally {
    if (browser) await browser.close()
    child.kill()
  }
}
main().catch(error => { console.error(error.stack); process.exitCode = 1 })
