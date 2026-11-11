import { useCallback, useEffect, useState } from 'react'
import type { View } from './types'

const views: View[] = ['landing', 'login', 'help', 'day', 'week', 'group', 'messages', 'feedback', 'admin', 'map']

export function viewFromUrl(url: string, authenticated: boolean): View {
  const location = new URL(url)
  const message = Number(location.searchParams.get('message'))
  if (Number.isInteger(message) && message > 0) return 'messages'
  const hash = location.hash.replace(/^#\/?/, '')
  if (views.includes(hash as View)) return hash as View
  // Preserve a separate administrative entry point as well as #/admin.
  if (/^\/admin\/?$/.test(location.pathname)) return 'admin'
  return authenticated ? 'day' : 'landing'
}

/** Hash routes work with static hosting, the PWA shell and Capacitor's local origin. */
export function useNavigation(authenticated: boolean) {
  const [view, updateView] = useState<View>(() => viewFromUrl(window.location.href, authenticated))
  useEffect(() => {
    const restore = () => updateView(viewFromUrl(window.location.href, authenticated))
    window.addEventListener('popstate', restore)
    window.addEventListener('hashchange', restore)
    return () => {
      window.removeEventListener('popstate', restore)
      window.removeEventListener('hashchange', restore)
    }
  }, [authenticated])
  const navigate = useCallback((next: View, replace = false) => {
    const url = new URL(window.location.href)
    url.hash = `/${next}`
    // A push link selects its message only once; never discard other query parameters.
    url.searchParams.delete('message')
    if (replace) window.history.replaceState(null, '', url)
    else if (url.href !== window.location.href) window.history.pushState(null, '', url)
    updateView(next)
    window.scrollTo({ top: 0 })
  }, [])
  return [view, navigate] as const
}
