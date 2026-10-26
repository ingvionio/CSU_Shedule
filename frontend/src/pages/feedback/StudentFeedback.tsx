import { useState, type FormEvent } from 'react'
import { CheckCircle2, RefreshCw, Send } from 'lucide-react'

import { useMyFeedback, useSendFeedback } from '../../api/queries'
import type { FeedbackKind, MyFeedback } from '../../types'
import { KIND_OPTIONS, STATUS_TITLES, feedbackDate, isEmail } from './labels'

type Tab = 'write' | 'mine'

/** Как на бэкенде: FeedbackIn.text min_length. */
const MIN_TEXT_LENGTH = 5

export function StudentFeedback({ groupId }: { groupId: number | null }) {
  const [tab, setTab] = useState<Tab>('write')
  const mine = useMyFeedback(tab === 'mine')
  const answered = (mine.data ?? []).filter((item) => item.status === 'answered').length

  return (
    <section className="feedback-screen">
      <div className="segmented">
        <button className={tab === 'write' ? 'active' : ''} onClick={() => setTab('write')}>Написать</button>
        <button className={tab === 'mine' ? 'active' : ''} onClick={() => setTab('mine')}>
          Мои обращения{answered ? ` · ${answered}` : ''}
        </button>
      </div>

      {tab === 'write'
        ? <FeedbackForm groupId={groupId} onShowMine={() => setTab('mine')} />
        : <MyFeedbackList items={mine.data} loading={mine.isLoading} error={mine.error as Error | null} onRetry={() => mine.refetch()} />}
    </section>
  )
}

function FeedbackForm({ groupId, onShowMine }: { groupId: number | null; onShowMine: () => void }) {
  const [kind, setKind] = useState<FeedbackKind>('methodist')
  const [text, setText] = useState('')
  const [authorName, setAuthorName] = useState('')
  const [contact, setContact] = useState('')
  const [consent, setConsent] = useState(false)
  const [website, setWebsite] = useState('')
  const [sent, setSent] = useState<{ id: number; kind_title: string } | null>(null)
  const [formError, setFormError] = useState('')
  const send = useSendFeedback()

  const hasPersonalData = Boolean(authorName.trim() || contact.trim())
  const hint = KIND_OPTIONS.find((option) => option.kind === kind)?.hint

  /** Почему форму нельзя отправить; пустая строка — можно. */
  const problem = text.trim().length < MIN_TEXT_LENGTH
    ? `Сообщение слишком короткое — напишите хотя бы ${MIN_TEXT_LENGTH} символов.`
    : hasPersonalData && !consent
      ? 'Отметьте согласие на обработку данных или очистите поля «Имя» и «Куда ответить».'
      : ''

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setFormError(problem)
    if (problem) return
    try {
      const result = await send.mutateAsync({
        kind,
        text: text.trim(),
        group_id: groupId,
        author_name: authorName.trim() || null,
        contact: contact.trim() || null,
        website,
      })
      setSent(result)
      setText('')
    } catch {
      // Ошибка показывается из send.error.
    }
  }

  if (sent) {
    return (
      <div className="screen-card selection-screen feedback-sent">
        <span className="feedback-sent-icon"><CheckCircle2 size={22} /></span>
        <h1>Обращение №{sent.id} отправлено</h1>
        <p className="muted">
          Адресат: {sent.kind_title}. Ответ появится в разделе «Мои обращения» на этом устройстве
          {isEmail(contact) ? ' и придёт на почту' : ''}.
        </p>
        <button className="button button-primary full" onClick={onShowMine}>Мои обращения</button>
        <button className="button button-secondary full" onClick={() => { setSent(null); send.reset() }}>Написать ещё</button>
      </div>
    )
  }

  return (
    <form className="screen-card selection-screen feedback-form" onSubmit={submit}>
      <div className="eyebrow">ОБРАТНАЯ СВЯЗЬ</div>
      <h1>Задать вопрос</h1>
      <p className="muted">Напишите методисту, в деканат или нам, разработчикам приложения.</p>

      <span className="field-label">Кому</span>
      <div className="feedback-kinds">
        {KIND_OPTIONS.map((option) => (
          <button
            type="button"
            key={option.kind}
            className={`choice ${kind === option.kind ? 'selected' : ''}`}
            onClick={() => setKind(option.kind)}
          >{option.label}</button>
        ))}
      </div>
      {hint && <p className="feedback-hint">{hint}</p>}

      <label className="field-label" htmlFor="feedback-text">Сообщение</label>
      <textarea
        id="feedback-text"
        className="text-field text-area"
        rows={5}
        maxLength={4000}
        value={text}
        placeholder="Опишите вопрос как можно подробнее"
        onChange={(event) => setText(event.target.value)}
      />

      <label className="field-label" htmlFor="feedback-name">Имя <span className="optional">— необязательно</span></label>
      <input
        id="feedback-name"
        className="text-field"
        maxLength={200}
        autoComplete="name"
        value={authorName}
        onChange={(event) => setAuthorName(event.target.value)}
      />

      <label className="field-label" htmlFor="feedback-contact">Куда ответить <span className="optional">— необязательно</span></label>
      <input
        id="feedback-contact"
        className="text-field"
        maxLength={200}
        autoComplete="email"
        placeholder="Email или @ник в телеграме"
        value={contact}
        onChange={(event) => setContact(event.target.value)}
      />
      <p className="feedback-hint">
        Ответ появится в «Мои обращения» на этом устройстве. Оставьте email — он придёт и на почту.
      </p>

      {hasPersonalData && (
        <label className="feedback-consent">
          <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
          <span>Согласен(на) на обработку указанных данных, чтобы мне ответили на обращение</span>
        </label>
      )}

      {/* Ловушка для ботов: человек это поле не видит. */}
      <input
        className="feedback-trap"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={website}
        onChange={(event) => setWebsite(event.target.value)}
      />

      {/* Ошибка исчезает, как только её причину исправили. */}
      {formError && problem && <p className="form-error" role="alert">{problem}</p>}
      {send.error && <p className="form-error" role="alert">{(send.error as Error).message}</p>}
      <button className="button button-primary full" disabled={send.isPending}>
        <Send size={16} />{send.isPending ? 'Отправляем…' : 'Отправить'}
      </button>
    </form>
  )
}

function MyFeedbackList({
  items,
  loading,
  error,
  onRetry,
}: {
  items?: MyFeedback[]
  loading: boolean
  error: Error | null
  onRetry: () => void
}) {
  if (loading && !items) return <div className="state-note">Загружаем обращения…</div>
  if (error && !items) {
    return (
      <div className="state-note error-note">
        <span>{error.message}</span>
        <button className="button button-secondary" onClick={onRetry}><RefreshCw size={16} />Повторить</button>
      </div>
    )
  }
  if (!items?.length) {
    return <div className="empty-day">Здесь появятся ваши обращения и ответы на них.</div>
  }

  return (
    <div className="feedback-list">
      {items.map((item) => (
        <article key={item.id} className="feedback-card">
          <div className="feedback-card-head">
            <span>{item.kind_title} · {feedbackDate(item.created_at)}</span>
            <span className={`badge feedback-status-${item.status}`}>{STATUS_TITLES[item.status]}</span>
          </div>
          <p className="feedback-text">{item.text}</p>
          {item.replies.map((reply) => (
            <div key={reply.id} className={`feedback-reply ${reply.author_kind}`}>
              <b>{reply.author_title} · {feedbackDate(reply.created_at)}</b>
              <p className="feedback-text">{reply.text}</p>
            </div>
          ))}
        </article>
      ))}
      <p className="feedback-hint centered-text">Обращения хранятся на этом устройстве. После входа через Moodle они будут видны везде.</p>
    </div>
  )
}
