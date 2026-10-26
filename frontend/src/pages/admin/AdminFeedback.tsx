import { useEffect, useState } from 'react'
import { Mail, RefreshCw, Send, X } from 'lucide-react'

import { ApiError } from '../../api/client'
import { useAdminFeedback, useFeedbackFolders, useFeedbackMutations, useFeedbackRecipients } from '../../api/queries'
import type { AdminFeedback as Feedback, FeedbackKind, FeedbackRecipient, FeedbackStatus } from '../../types'
import { KIND_TITLES, STATUS_TITLES, feedbackDate } from '../feedback/labels'

const FOLDERS: FeedbackKind[] = ['unknown', 'methodist', 'deanery', 'dev']
const STATUS_FILTERS: { value: FeedbackStatus | ''; label: string }[] = [
  { value: '', label: 'Все' },
  { value: 'new', label: 'Новые' },
  { value: 'in_progress', label: 'В работе' },
  { value: 'answered', label: 'С ответом' },
  { value: 'archived', label: 'Закрытые' },
]

type AdminFeedbackProps = {
  token: string
  /** Токен истёк или недействителен — нужно войти заново. */
  onUnauthorized: () => void
}

export function AdminFeedback({ token, onUnauthorized }: AdminFeedbackProps) {
  const [kind, setKind] = useState<FeedbackKind>(FOLDERS[0])
  const [status, setStatus] = useState<FeedbackStatus | ''>('')
  const [openId, setOpenId] = useState<number | null>(null)
  const [showRecipients, setShowRecipients] = useState(false)

  const folders = useFeedbackFolders(token)
  const list = useAdminFeedback(token, kind, status)
  const opened = list.data?.find((item) => item.id === openId) ?? null

  useEffect(() => {
    if ([folders.error, list.error].some((error) => error instanceof ApiError && error.status === 401)) onUnauthorized()
  }, [folders.error, list.error, onUnauthorized])

  const countOf = (folder: FeedbackKind) => folders.data?.find((item) => item.kind === folder)

  return (
    <section className="admin-schedule">
      <div className="admin-schedule-heading">
        <span className="eyebrow">АДМИНИСТРИРОВАНИЕ</span>
        <h1>Обращения</h1>
        <p className="muted">Вопросы и предложения студентов. Ответ студент увидит в приложении.</p>
      </div>

      <div className="feedback-folders" aria-label="Папки">
        {FOLDERS.map((folder) => {
          const count = countOf(folder)
          return (
            <button
              key={folder}
              className={kind === folder ? 'active' : ''}
              onClick={() => { setKind(folder); setOpenId(null) }}
            >
              <span>{KIND_TITLES[folder]}</span>
              {count?.new ? <b className="feedback-count">{count.new}</b> : <small>{count?.total ?? ''}</small>}
            </button>
          )
        })}
      </div>

      <div className="feedback-filters">
        {STATUS_FILTERS.map((filter) => (
          <button
            key={filter.value}
            className={`choice ${status === filter.value ? 'selected' : ''}`}
            onClick={() => setStatus(filter.value)}
          >{filter.label}</button>
        ))}
      </div>

      {list.isError && !(list.error instanceof ApiError && list.error.status === 401) && (
        <div className="state-note error-note">
          <span>{(list.error as Error).message}</span>
          <button className="button button-secondary" onClick={() => list.refetch()}><RefreshCw size={16} />Повторить</button>
        </div>
      )}
      {list.isLoading && <div className="state-note">Загружаем обращения…</div>}
      {list.data && !list.data.length && <div className="empty-day">В этой папке пока пусто.</div>}

      <div className="feedback-list">
        {list.data?.map((item) => (
          <button key={item.id} className={`feedback-card feedback-card-button ${item.status === 'new' ? 'unread' : ''}`} onClick={() => setOpenId(item.id)}>
            <div className="feedback-card-head">
              <span>№{item.id} · {item.group_name ?? 'без группы'} · {feedbackDate(item.created_at)}</span>
              <span className={`badge feedback-status-${item.status}`}>{STATUS_TITLES[item.status]}</span>
            </div>
            <p className="feedback-text clamp">{item.text}</p>
            {(item.author_name || item.replies.length > 0) && (
              <small className="feedback-card-meta">
                {item.author_name ?? 'Аноним'}{item.replies.length ? ` · ответов: ${item.replies.length}` : ''}
              </small>
            )}
          </button>
        ))}
      </div>

      <button className="quiet-link" onClick={() => setShowRecipients((value) => !value)}>
        <Mail size={14} />{showRecipients ? 'Скрыть адресатов' : 'Адресаты и почта'}
      </button>
      {showRecipients && <RecipientsEditor token={token} />}

      {opened && <FeedbackDialog item={opened} token={token} onClose={() => setOpenId(null)} onUnauthorized={onUnauthorized} />}
    </section>
  )
}

function FeedbackDialog({
  item,
  token,
  onClose,
  onUnauthorized,
}: {
  item: Feedback
  token: string
  onClose: () => void
  onUnauthorized: () => void
}) {
  const [answer, setAnswer] = useState('')
  const [note, setNote] = useState(item.admin_note ?? '')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const { update, reply } = useFeedbackMutations(token)
  const busy = update.isPending || reply.isPending

  useEffect(() => {
    setNote(item.admin_note ?? '')
  }, [item.id, item.admin_note])

  const run = async (action: () => Promise<unknown>, done: string) => {
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(done)
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) onUnauthorized()
      else setError((reason as Error).message)
    }
  }

  const sendAnswer = () => run(async () => {
    await reply.mutateAsync({ id: item.id, text: answer.trim() })
    setAnswer('')
  }, item.contact_is_email ? 'Ответ отправлен: в приложение и на почту студента.' : 'Ответ отправлен в приложение.')

  const move = (kind: FeedbackKind) => run(
    () => update.mutateAsync({ id: item.id, body: { kind } }),
    `Перенесено в папку «${KIND_TITLES[kind]}». Адресату ушло письмо, если у него указана почта.`,
  )

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="confirm-modal feedback-dialog" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <button className="modal-close" aria-label="Закрыть" onClick={onClose}><X size={17} /></button>
        <span className="eyebrow">ОБРАЩЕНИЕ №{item.id}</span>

        <dl className="feedback-meta">
          <dt>Группа</dt><dd>{item.group_name ?? '—'}</dd>
          <dt>Автор</dt><dd>{item.author_name ?? 'Аноним'}</dd>
          <dt>Контакт</dt><dd>{item.contact ?? '—'}</dd>
          <dt>Получено</dt><dd>{feedbackDate(item.created_at)}{item.recipient_title ? ` · ${item.recipient_title}` : ''}</dd>
        </dl>

        <p className="feedback-text feedback-original">{item.text}</p>

        {item.replies.map((entry) => (
          <div key={entry.id} className={`feedback-reply ${entry.author_kind}`}>
            <b>{entry.author_title}{entry.author_name ? ` (${entry.author_name})` : ''} · {feedbackDate(entry.created_at)}</b>
            <p className="feedback-text">{entry.text}</p>
          </div>
        ))}

        <label className="admin-field">
          <span>Ответ студенту</span>
          <textarea className="text-field text-area" rows={4} maxLength={4000} value={answer} onChange={(event) => setAnswer(event.target.value)} />
        </label>
        <p className="admin-dialog-hint">
          {item.contact_is_email
            ? 'Студент увидит ответ в приложении и получит его на почту.'
            : 'Студент увидит ответ в приложении на своём устройстве.'}
        </p>
        <button className="button button-primary full" disabled={busy || !answer.trim()} onClick={sendAnswer}>
          <Send size={16} />Ответить
        </button>

        <div className="admin-time-row">
          <label className="admin-field">
            <span>Статус</span>
            <select
              className="select-field"
              value={item.status}
              disabled={busy}
              onChange={(event) => run(
                () => update.mutateAsync({ id: item.id, body: { status: event.target.value as FeedbackStatus } }),
                'Статус изменён.',
              )}
            >
              {(Object.keys(STATUS_TITLES) as FeedbackStatus[]).map((value) => (
                <option key={value} value={value}>{STATUS_TITLES[value]}</option>
              ))}
            </select>
          </label>
          <label className="admin-field">
            <span>Папка</span>
            <select
              className="select-field"
              value={item.kind}
              disabled={busy}
              onChange={(event) => move(event.target.value as FeedbackKind)}
            >
              {FOLDERS.map((folder) => <option key={folder} value={folder}>{KIND_TITLES[folder]}</option>)}
            </select>
          </label>
        </div>

        <label className="admin-field">
          <span>Заметка для своих (студент не видит)</span>
          <textarea className="text-field text-area" rows={2} maxLength={1000} value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        {note !== (item.admin_note ?? '') && (
          <button
            className="button button-secondary full"
            disabled={busy}
            onClick={() => run(() => update.mutateAsync({ id: item.id, body: { admin_note: note } }), 'Заметка сохранена.')}
          >Сохранить заметку</button>
        )}

        {notice && <p className="success-note">{notice}</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
      </div>
    </div>
  )
}

function RecipientsEditor({ token }: { token: string }) {
  const recipients = useFeedbackRecipients(token)

  if (recipients.isLoading) return <div className="state-note">Загружаем адресатов…</div>
  if (recipients.isError) return <p className="form-error">{(recipients.error as Error).message}</p>

  return (
    <div className="feedback-recipients">
      <p className="muted">Обращения из папки дублируются на эти адреса. Несколько адресов — через запятую.</p>
      {recipients.data?.map((recipient) => <RecipientRow key={recipient.id} recipient={recipient} token={token} />)}
    </div>
  )
}

function RecipientRow({ recipient, token }: { recipient: FeedbackRecipient; token: string }) {
  const [emails, setEmails] = useState(recipient.emails.join(', '))
  const [message, setMessage] = useState('')
  const [failed, setFailed] = useState(false)
  const { updateRecipient } = useFeedbackMutations(token)

  const save = async (body: Parameters<typeof updateRecipient.mutateAsync>[0]['body']) => {
    setMessage('')
    try {
      const saved = await updateRecipient.mutateAsync({ id: recipient.id, body })
      setEmails(saved.emails.join(', '))
      setFailed(false)
      setMessage('Сохранено')
    } catch (reason) {
      setFailed(true)
      setMessage((reason as Error).message)
    }
  }

  const parsed = emails.split(/[,;\s]+/).map((value) => value.trim()).filter(Boolean)
  const changed = parsed.join(',') !== recipient.emails.join(',')

  return (
    <div className="recipient-row">
      <div className="recipient-head">
        <strong>{recipient.title}</strong>
        <label>
          <input
            type="checkbox"
            checked={recipient.is_active}
            disabled={updateRecipient.isPending}
            onChange={(event) => save({ is_active: event.target.checked })}
          />
          <span>Письма включены</span>
        </label>
      </div>
      <div className="recipient-edit">
        <input
          className="text-field"
          placeholder="Без почты — только в админке"
          value={emails}
          onChange={(event) => setEmails(event.target.value)}
        />
        <button className="button button-secondary" disabled={!changed || updateRecipient.isPending} onClick={() => save({ emails: parsed })}>
          Сохранить
        </button>
      </div>
      {message && <small className={failed ? 'recipient-error' : 'recipient-saved'}>{message}</small>}
    </div>
  )
}
