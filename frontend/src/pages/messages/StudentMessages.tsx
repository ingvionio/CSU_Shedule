import { useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, RefreshCw, UserRound, X } from 'lucide-react'

import { useInbox, useInboxMutations } from '../../api/queries'
import { registerStudent, useStudentSession } from '../../api/student'
import type { Group, InboxMessage } from '../../types'
import { IMPORTANCE_TITLES, messageDate } from './labels'

type StudentMessagesProps = {
  group: Group | undefined
  /** Группа не выбрана — отправить на экран выбора. */
  onChooseGroup: () => void
}

export function StudentMessages({ group, onChooseGroup }: StudentMessagesProps) {
  const session = useStudentSession()
  const inbox = useInbox(session !== null)
  const [openId, setOpenId] = useState<number | null>(null)
  const opened = inbox.data?.messages.find((item) => item.id === openId) ?? null

  if (!session) return <ProfileForm group={group} onChooseGroup={onChooseGroup} />

  return (
    <section className="feedback-screen">
      <div className="profile-line">
        <UserRound size={16} />
        <span>{session.profile.full_name} · {session.profile.group_name ?? 'без группы'}</span>
      </div>

      {inbox.isError && !inbox.data && (
        <div className="state-note error-note">
          <span>{(inbox.error as Error).message}</span>
          <button className="button button-secondary" onClick={() => inbox.refetch()}><RefreshCw size={16} />Повторить</button>
        </div>
      )}
      {inbox.isLoading && !inbox.data && <div className="state-note">Загружаем сообщения…</div>}
      {inbox.data && !inbox.data.messages.length && (
        <div className="empty-day">Здесь появятся сообщения от методиста и деканата.</div>
      )}

      <div className="feedback-list">
        {inbox.data?.messages.map((item) => (
          <button
            key={item.id}
            className={`feedback-card feedback-card-button ${item.is_unread ? 'unread' : ''}`}
            onClick={() => setOpenId(item.id)}
          >
            <div className="feedback-card-head">
              <span>{messageDate(item.sent_at)}</span>
              <MessageBadge item={item} />
            </div>
            <strong className="message-title">{item.title}</strong>
            <p className="feedback-text clamp">{item.body}</p>
          </button>
        ))}
      </div>

      {opened && <MessageDialog item={opened} onClose={() => setOpenId(null)} />}
    </section>
  )
}

function MessageBadge({ item }: { item: InboxMessage }) {
  if (item.requires_ack && !item.acknowledged_at) return <span className="badge importance-high">Нужно подтвердить</span>
  if (item.importance === 'high') return <span className="badge feedback-status-answered">Ознакомлен</span>
  if (item.is_unread) return <span className="badge feedback-status-new">Новое</span>
  return null
}

function MessageDialog({ item, onClose }: { item: InboxMessage; onClose: () => void }) {
  const { open, acknowledge } = useInboxMutations()
  const [error, setError] = useState('')

  // Открытие сообщения — это и есть «прочитано».
  useEffect(() => {
    if (!item.read_at) open.mutate(item.id)
  }, [item.id])

  const confirm = async () => {
    setError('')
    try {
      await acknowledge.mutateAsync(item.id)
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="confirm-modal feedback-dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}><X size={17} /></button>
        <span className="eyebrow">{IMPORTANCE_TITLES[item.importance].toUpperCase()} · {messageDate(item.sent_at)}</span>
        <h2>{item.title}</h2>
        <p className="feedback-text">{item.body}</p>

        {item.requires_ack && (item.acknowledged_at
          ? <p className="success-note"><CheckCircle2 size={16} />Вы подтвердили {messageDate(item.acknowledged_at)}</p>
          : <button className="button button-primary full" disabled={acknowledge.isPending} onClick={confirm}>
            <CheckCircle2 size={16} />{acknowledge.isPending ? 'Отправляем…' : 'Ознакомлен'}
          </button>)}
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>
    </div>
  )
}

function ProfileForm({ group, onChooseGroup }: { group: Group | undefined; onChooseGroup: () => void }) {
  const [name, setName] = useState('')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!group) return
    setBusy(true)
    setError('')
    try {
      await registerStudent(name, group.id)
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="screen-card selection-screen feedback-form" onSubmit={submit}>
      <div className="eyebrow">СООБЩЕНИЯ</div>
      <h1>Кто вы?</h1>
      <p className="muted">
        Методист отправляет сообщения группе, курсу или лично вам. Укажите фамилию и имя — по ним
        методист увидит, что вы прочитали важное сообщение. Профиль привязан к этому устройству.
      </p>

      <label className="field-label" htmlFor="profile-name">Фамилия и имя</label>
      <input
        id="profile-name"
        className="text-field"
        maxLength={200}
        autoComplete="name"
        placeholder="Иванов Иван"
        value={name}
        onChange={(event) => setName(event.target.value)}
      />

      <span className="field-label">Группа</span>
      {group
        ? <button type="button" className="select-field" onClick={onChooseGroup}>{group.name}<span className="optional">изменить</span></button>
        : <button type="button" className="button button-secondary full" onClick={onChooseGroup}>Выбрать группу</button>}

      <label className="feedback-consent">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
        <span>Согласен(на) на обработку ФИО и группы, чтобы получать сообщения и подтверждать прочтение</span>
      </label>

      {error && <p className="form-error" role="alert">{error}</p>}
      <button className="button button-primary full" disabled={busy || !group || !consent || name.trim().length < 3}>
        {busy ? 'Сохраняем…' : 'Получать сообщения'}
      </button>
    </form>
  )
}
