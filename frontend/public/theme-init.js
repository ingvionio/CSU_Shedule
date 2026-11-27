/* Тема нужна до первой отрисовки, ещё до загрузки React. */
(() => {
  const key = 'csu-schedule:appearance'
  const system = window.matchMedia('(prefers-color-scheme: dark)')
  const root = document.documentElement
  const themeColor = document.querySelector('meta[name="theme-color"]')
  const lightColor = themeColor.content
  const darkColor = themeColor.dataset.dark
  const listeners = new Set()
  const normalize = (value) => value === 'dark' || value === 'system' ? value : 'light'
  let preference = 'light'
  let storage
  try {
    storage = window.localStorage
    preference = normalize(storage.getItem(key))
  } catch {
    // Хранилище может быть отключено в браузере.
  }

  function apply() {
    const dark = preference === 'dark' || (preference === 'system' && system.matches)
    root.dataset.theme = dark ? 'dark' : 'light'
    themeColor.content = dark ? darkColor : lightColor
    listeners.forEach((listener) => listener())
  }

  function update(value) {
    const next = normalize(value)
    if (preference === next) return
    preference = next
    apply()
  }

  apply()
  system.addEventListener('change', () => {
    if (preference === 'system') apply()
  })
  window.addEventListener('storage', (event) => {
    if ((event.key === key || event.key === null) && event.storageArea === storage) {
      update(event.newValue)
    }
  })

  window.iitTheme = {
    getPreference: () => preference,
    setPreference(value) {
      const next = normalize(value)
      try {
        storage?.setItem(key, next)
      } catch {
        // В этой вкладке переключение работает и без сохранения.
      }
      update(next)
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
})()
