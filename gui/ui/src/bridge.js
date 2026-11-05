/**
 * 通往後端的唯一入口：頁面 → pywebview 的 `js_api` → `gui/api.py`。
 *
 * ⚠ 一律用 `import { api }`，不要直接使用 `window.pywebview`：注入完成之前是 undefined。
 */

const listeners = new Set()

function fanout(event, data) {
  for (const fn of listeners) {
    try {
      fn(event, data)
    } catch (e) {
      console.error('[bridge] 事件處理失敗', event, e)
    }
  }
}

/**
 * 等 `pywebviewready`：`window.pywebview.api` 在注入之後才存在，每次呼叫都先等這個 Promise。
 */
function whenReady() {
  return new Promise((resolve) => {
    if (window.pywebview?.api) {
      resolve()
      return
    }
    window.addEventListener('pywebviewready', () => resolve(), { once: true })
  })
}

function shell() {
  // 後端推事件走這裡（`Channel._emit` 會呼叫 `window.__recv([...])`）
  window.__recv = (events) => {
    for (const e of events) fanout(e.event, e.data)
  }

  const call = async (method, params = {}) => {
    await whenReady()
    const fn = window.pywebview.api[method]
    if (typeof fn !== 'function') {
      return { ok: false, error: `後端沒有這個方法：${method}` }
    }
    try {
      return { ok: true, result: await fn(params) }
    } catch (e) {
      // pywebview 把 Python 的例外包成 JS 的 Error，訊息是中文
      return { ok: false, error: String(e?.message || e) }
    }
  }

  const closeHandlers = new Set()
  const closingHandlers = new Set()
  // 視窗的 ✕ 由 Python 那側攔下來，再用事件問前端要怎麼做
  listeners.add((event) => {
    if (event === 'confirm_close') for (const fn of closeHandlers) fn()
    if (event === 'closing') for (const fn of closingHandlers) fn()
  })

  return {
    call,
    on(handler) {
      listeners.add(handler)
      return () => listeners.delete(handler)
    },
    win: {
      minimize: () => call('win_minimize'),
      toggleMaximize: () => call('win_toggle_maximize'),
      isMaximized: async () => (await call('win_is_maximized')).result?.value ?? false,
      close: () => call('win_close')
    },
    app: {
      hide: () => call('win_hide'),
      quit: () => call('win_quit'),
      openExternal: (url) => call('open_external', { url }),
      onConfirmClose(fn) {
        closeHandlers.add(fn)
        return () => closeHandlers.delete(fn)
      },
      onClosing(fn) {
        closingHandlers.add(fn)
        return () => closingHandlers.delete(fn)
      }
    }
  }
}

export const api = shell()
