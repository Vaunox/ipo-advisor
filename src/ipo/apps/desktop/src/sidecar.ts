// Sidecar lifecycle for the bundled Python FastAPI engine — the build-critical part (Deep Dive #6):
//   * free-port selection (never a hardcoded port that could collide),
//   * a /health readiness gate the UI waits behind (no cold-start race),
//   * clean teardown on every exit path (no orphaned python).
// Pure Node (no electron import) so it can be self-tested headlessly: `node dist/sidecar.js`.

import { spawn, type ChildProcess } from 'node:child_process'
import fs from 'node:fs'
import { get as httpGet } from 'node:http'
import net from 'node:net'
import path from 'node:path'

export interface SpawnOpts {
  dev: boolean
  repoRoot: string
  /** Path to the bundled PyInstaller engine binary (prod only). */
  enginePath?: string
}

/** Ask the OS for a free TCP port on 127.0.0.1. */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer()
    srv.on('error', reject)
    srv.listen(0, '127.0.0.1', () => {
      const addr = srv.address()
      const port = typeof addr === 'object' && addr ? addr.port : 0
      srv.close(() => resolve(port))
    })
  })
}

/** Walk up from `start` until a directory with pyproject.toml (the repo root) is found. */
export function findRepoRoot(start: string): string {
  let dir = start
  for (let i = 0; i < 10; i++) {
    if (fs.existsSync(path.join(dir, 'pyproject.toml'))) return dir
    const parent = path.dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return start
}

/** Spawn the engine on `port`. Dev runs the module from source with the venv python; prod runs the
 *  bundled PyInstaller binary. stdout/stderr are piped so the shell can log/observe the engine. */
export function spawnEngine(port: number, opts: SpawnOpts): ChildProcess {
  if (opts.dev) {
    const py =
      process.platform === 'win32'
        ? path.join(opts.repoRoot, '.venv', 'Scripts', 'python.exe')
        : path.join(opts.repoRoot, '.venv', 'bin', 'python')
    return spawn(py, ['-m', 'ipo.service.runner', '--port', String(port)], {
      cwd: opts.repoRoot,
      env: { ...process.env, PYTHONPATH: path.join(opts.repoRoot, 'src'), PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  }
  if (!opts.enginePath) throw new Error('enginePath is required in production')
  return spawn(opts.enginePath, ['--port', String(port)], { stdio: ['ignore', 'pipe', 'pipe'] })
}

/** Poll GET {base}/health until it returns 200, or the timeout elapses. */
export function waitForHealth(base: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve) => {
    const retry = () => {
      if (Date.now() >= deadline) return resolve(false)
      setTimeout(tryOnce, 300)
    }
    const tryOnce = () => {
      const req = httpGet(`${base}/health`, (res) => {
        res.resume()
        if (res.statusCode === 200) resolve(true)
        else retry()
      })
      req.on('error', retry)
      req.setTimeout(1500, () => req.destroy())
    }
    tryOnce()
  })
}

/** Kill the engine and its whole process tree (uvicorn may spawn children). Idempotent. */
export function killEngine(child: ChildProcess | null): void {
  if (!child || child.killed || child.pid == null) return
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    } else {
      child.kill('SIGTERM')
    }
  } catch {
    /* already gone */
  }
}

// --- headless self-test: spawn → health → kill, verifying the lifecycle without a GUI ---
if (require.main === module) {
  ;(async () => {
    const root = findRepoRoot(__dirname)
    const port = await freePort()
    const base = `http://127.0.0.1:${port}`
    console.log(`[selftest] repoRoot=${root}`)
    console.log(`[selftest] free port ${port}`)
    const child = spawnEngine(port, { dev: true, repoRoot: root })
    child.stderr?.on('data', (d) => process.stderr.write(`[engine] ${d}`))
    const t0 = Date.now()
    const ready = await waitForHealth(base, 30000)
    console.log(`[selftest] /health ${ready ? 'GREEN' : 'TIMEOUT'} after ${Date.now() - t0}ms`)
    killEngine(child)
    setTimeout(() => {
      console.log('[selftest] engine killed — done')
      process.exit(ready ? 0 : 1)
    }, 1200)
  })().catch((e) => {
    console.error('[selftest] error', e)
    process.exit(2)
  })
}
