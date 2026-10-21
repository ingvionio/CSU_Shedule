import { useState, type FormEvent } from 'react'
import { LogIn } from 'lucide-react'

import { api } from '../../api/client'
import type { AdminSession } from '../../types'

export function AdminLogin({ onLogin }: { onLogin: (session: AdminSession) => void }) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const response = await api.adminLogin(login.trim(), password)
      onLogin({ token: response.access_token, expires_at: response.expires_at })
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="screen-card selection-screen admin-login" onSubmit={submit}>
      <div className="eyebrow">АДМИНИСТРИРОВАНИЕ</div>
      <h1>Вход для администратора</h1>
      <p className="muted">Изменения расписания сразу видят студенты.</p>

      <label className="field-label" htmlFor="admin-login">Логин</label>
      <input
        id="admin-login"
        className="text-field"
        autoComplete="username"
        value={login}
        onChange={(event) => setLogin(event.target.value)}
      />
      <label className="field-label" htmlFor="admin-password">Пароль</label>
      <input
        id="admin-password"
        className="text-field"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary full" disabled={busy || !login.trim() || !password}>
        <LogIn size={17} />{busy ? 'Входим…' : 'Войти'}
      </button>
    </form>
  )
}
