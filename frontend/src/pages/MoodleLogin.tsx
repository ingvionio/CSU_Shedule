import { useState, type FormEvent } from 'react'
import { GraduationCap, LogIn, ShieldCheck } from 'lucide-react'

import { loginWithMoodle } from '../api/student'
import type { StudentSession } from '../api/types'

interface MoodleLoginProps {
  onLogin: (session: StudentSession) => void
  onGoToAdmin?: () => void
}

export function MoodleLogin({ onLogin, onGoToAdmin }: MoodleLoginProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError('')
    try {
      const session = await loginWithMoodle(username.trim(), password)
      onLogin(session)
    } catch (reason) {
      setError((reason as Error).message || 'Не удалось выполнить вход')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="screen-card selection-screen admin-login" onSubmit={submit}>
      <div className="eyebrow" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <GraduationCap size={16} /> ЧЕЛГУ · ИНСТИТУТ ИТ
      </div>
      <h1>Вход через Moodle</h1>
      <p className="muted">
        Войдите со своим логином и паролем от личного кабинета Moodle (<code>eu.iit.csu.ru</code>).
        Ваша академическая группа и расписание определятся автоматически.
      </p>

      <label className="field-label" htmlFor="moodle-username">
        Логин Moodle
      </label>
      <input
        id="moodle-username"
        className="text-field"
        autoComplete="username"
        autoCapitalize="none"
        placeholder="например, ivanov_ii"
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        disabled={busy}
      />

      <label className="field-label" htmlFor="moodle-password">
        Пароль
      </label>
      <input
        id="moodle-password"
        className="text-field"
        type="password"
        autoComplete="current-password"
        placeholder="••••••••"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        disabled={busy}
      />

      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '11px',
          color: '#6c757d',
          marginTop: '6px',
          marginBottom: '14px',
        }}
      >
        <ShieldCheck size={16} style={{ color: '#28a745', flexShrink: 0 }} />
        <span>Пароль шифруется и передаётся исключительно на сервер Moodle ЧелГУ.</span>
      </div>

      <button
        className="button button-primary full"
        disabled={busy || !username.trim() || !password}
        type="submit"
      >
        <LogIn size={17} />
        {busy ? 'Проверяем данные…' : 'Войти в расписание'}
      </button>

      {onGoToAdmin && (
        <div style={{ marginTop: '20px', textAlign: 'center' }}>
          <button
            type="button"
            className="button button-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
            onClick={onGoToAdmin}
          >
            Вход для администратора
          </button>
        </div>
      )}
    </form>
  )
}
