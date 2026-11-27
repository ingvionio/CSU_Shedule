import { useSyncExternalStore } from 'react'

type ThemePreference = 'light' | 'dark' | 'system'

declare global {
  interface Window {
    iitTheme?: {
      getPreference: () => ThemePreference
      setPreference: (preference: ThemePreference) => void
      subscribe: (listener: () => void) => () => void
    }
  }
}

const choices = [
  ['light', 'Светлая'],
  ['dark', 'Тёмная'],
  ['system', 'Системная'],
] as const
const lightPreference = () => 'light' as const
const emptySubscribe = () => () => {}

export function ThemeSetting() {
  const theme = window.iitTheme
  const preference = useSyncExternalStore(theme?.subscribe ?? emptySubscribe, theme?.getPreference ?? lightPreference)

  return (
    <label className="theme-setting">
      <span>Оформление</span>
      <select className="select-field" value={preference} disabled={!theme} onChange={(event) => {
        const choice = choices.find(([value]) => value === event.target.value)
        if (choice) theme?.setPreference(choice[0])
      }}>
        {choices.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>
  )
}
