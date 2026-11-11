import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const source = readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText

function loadClient({
  envApiUrl = undefined,
  isNative = false,
  origin = 'http://localhost:5173',
  protocol = 'http:',
  mockFetch = undefined,
} = {}) {
  const window = {
    location: {
      origin,
      protocol,
      hostname: origin.replace(/https?:\/\//, '').split(':')[0],
      port: origin.split(':')[2] || '',
    },
  }

  const capacitor = {
    Capacitor: {
      isNativePlatform: () => isNative,
      getPlatform: () => (isNative ? 'android' : 'web'),
    },
  }

  const mockMeta = {
    env: {
      VITE_API_URL: envApiUrl,
    },
  }

  const exports = {}
  const sandbox = {
    exports,
    module: { exports },
    require: (name) => {
      if (name === '@capacitor/core') return capacitor
      return require(name)
    },
    window,
    fetch: mockFetch || (() => Promise.reject(new Error('Fetch not mocked'))),
    FormData: class FormData {},
    import: { meta: mockMeta },
  }

  // TypeScript compiles `import.meta.env` to something or keeps it depending on config
  // Replace import.meta with a shim in the transpiled code if needed
  const instrumented = code.replace(/import\.meta/g, '({ env: { VITE_API_URL: ' + JSON.stringify(envApiUrl) + ' } })')

  vm.runInNewContext(instrumented, sandbox)
  return { exports: sandbox.module.exports, window }
}

test('resolveApiBaseUrl: defaults to /api/v1 for web on localhost:5173', () => {
  const { exports } = loadClient({ origin: 'http://localhost:5173' })
  assert.equal(exports.resolveApiBaseUrl(), '/api/v1')
})

test('resolveApiBaseUrl: defaults to /api/v1 for production web', () => {
  const { exports } = loadClient({ origin: 'https://iit-app.ru', protocol: 'https:' })
  assert.equal(exports.resolveApiBaseUrl(), '/api/v1')
})

test('resolveApiBaseUrl: returns https://iit-app.ru/api/v1 for Capacitor native platform', () => {
  const { exports } = loadClient({ isNative: true, origin: 'https://localhost', protocol: 'https:' })
  assert.equal(exports.resolveApiBaseUrl(), 'https://iit-app.ru/api/v1')
})

test('resolveApiBaseUrl: returns https://iit-app.ru/api/v1 for Android WebView (https://localhost)', () => {
  const { exports } = loadClient({ isNative: false, origin: 'https://localhost', protocol: 'https:' })
  assert.equal(exports.resolveApiBaseUrl(), 'https://iit-app.ru/api/v1')
})

test('resolveApiBaseUrl: respects custom VITE_API_URL', () => {
  const { exports } = loadClient({ envApiUrl: 'http://custom-server:9000/' })
  assert.equal(exports.resolveApiBaseUrl(), 'http://custom-server:9000/api/v1')
})

test('request: handles HTML response gracefully without SyntaxError on JSON parse', async () => {
  let requestedUrl = ''
  const mockFetch = async (url) => {
    requestedUrl = url
    return {
      status: 200,
      ok: true,
      headers: {
        get: (h) => (h.toLowerCase() === 'content-type' ? 'text/html; charset=utf-8' : null),
      },
      text: async () => '<!doctype html><html><body>Error</body></html>',
      json: async () => {
        throw new SyntaxError("Unexpected token '<', \"<!doctype \"... is not valid JSON")
      },
    }
  }

  const { exports } = loadClient({
    isNative: true,
    origin: 'https://localhost',
    mockFetch,
  })

  // Attempt login
  await assert.rejects(
    async () => {
      await exports.api.moodleLogin('test', 'secret')
    },
    (err) => {
      assert.equal(err.name, 'Error')
      assert.match(err.message, /некорректный ответ|ожидался JSON/i)
      assert.doesNotMatch(err.message, /Unexpected token/i)
      return true
    }
  )

  assert.equal(requestedUrl, 'https://iit-app.ru/api/v1/auth/moodle/login')
})
