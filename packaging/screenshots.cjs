// Capture Microsoft Store screenshots of the real app renderer to PNG files.
//
// Loads the running PWA dev server (localhost:5173, which proxies /api -> the engine on :8000) in a
// frameless BrowserWindow sized to the Store's minimum (1366x768) so webContents.capturePage()
// yields exactly that resolution, then walks the screens and writes one PNG each.
//
//   (start engine on :8000 and `npm run dev` for the pwa on :5173, then)
//   npx electron packaging/screenshots.cjs

const { app, BrowserWindow } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

const OUT = path.join(__dirname, '..', 'store-assets', 'screenshots')
const URL = 'http://localhost:5173'
const W = 1366
const H = 768

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function shot(win, name) {
  await sleep(900)
  const img = await win.webContents.capturePage()
  const file = path.join(OUT, `${name}.png`)
  fs.writeFileSync(file, img.toPNG())
  const size = img.getSize()
  console.log(`saved ${name}.png  ${size.width}x${size.height}`)
}

async function nav(win, label) {
  await win.webContents.executeJavaScript(
    `(() => { const b=[...document.querySelectorAll('.nav button')].find(x=>new RegExp('${label}','i').test(x.textContent)); if(b) b.click(); })()`,
  )
  await sleep(900)
}

app.whenReady().then(async () => {
  fs.mkdirSync(OUT, { recursive: true })
  const win = new BrowserWindow({
    width: W,
    height: H,
    frame: false,
    show: true,
    backgroundColor: '#0a0d12',
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })
  await win.loadURL(URL)
  await sleep(2600) // load + data fetch + entrance animation settle

  await shot(win, '1-live-signals')

  // Verdict detail (open the Zomato row), pinned to the top so the hero shows
  await win.webContents.executeJavaScript(
    `(()=>{const n=[...document.querySelectorAll('.co .name')].find(x=>/Zomato/i.test(x.textContent)); if(n) n.closest('.row').click();})()`,
  )
  await sleep(900)
  await win.webContents.executeJavaScript(`document.querySelector('.main').scrollTop = 0`)
  await sleep(500)
  await shot(win, '2-verdict-detail')

  // Second detail shot: scroll to the contribution bars + subscription + demand sparkline
  await win.webContents.executeJavaScript(`document.querySelector('.main').scrollTop = 470`)
  await sleep(500)
  await shot(win, '3-verdict-explained')

  await nav(win, 'History')
  await win.webContents.executeJavaScript(`document.querySelector('.main').scrollTop = 0`)
  await sleep(400)
  await shot(win, '4-history')

  await nav(win, 'Upcoming')
  await shot(win, '5-upcoming')

  await nav(win, 'Settings')
  await shot(win, '6-settings')

  console.log(`\nscreenshots written to ${OUT}`)
  app.quit()
})
