import { ContextHelp } from '../../ContextHelp'
import { useState, type FormEvent } from 'react'
import { CheckCircle2, FileText, RefreshCw, Send } from 'lucide-react'

import { useSendFeedback, type useMyFeedback } from '../../api/queries'
import type { StudentProfile } from '../../api/types'
import type { MyFeedback, QuestionKind } from '../../types'
import { KIND_OPTIONS, STATUS_TITLES, feedbackDate, isEmail } from './labels'

type Tab = 'write' | 'mine'

/** Как на бэкенде: FeedbackIn.text min_length. */
const MIN_TEXT_LENGTH = 5
const MAX_CERTIFICATE_COPIES = 2_147_483_647

type StudentFeedbackProps = {
  profile: StudentProfile
  certificateMode: boolean
  mine: ReturnType<typeof useMyFeedback>
  updates: ReadonlyMap<number, string>
  onMarkSeen: (item: MyFeedback) => void
  onOrderCertificate: () => void
  onOpenFeedback: () => void
}

export function StudentFeedback({ profile, certificateMode, mine, updates, onMarkSeen, onOrderCertificate, onOpenFeedback }: StudentFeedbackProps) {
  const [tab, setTab] = useState<Tab>('write')
  const showTab = (next: Tab) => {
    setTab(next)
    if (certificateMode) onOpenFeedback()
  }

  return (
    <section className="feedback-screen">
      {certificateMode
        ? <ContextHelp ids={['certificate']} label="Как заказать справку" />
        : <ContextHelp ids={['feedback']} label="Как отправить обращение" />}
      {!certificateMode && (
        <button type="button" className="button button-secondary full certificate-action" onClick={onOrderCertificate}>
          <FileText size={18} />Заказать справку
        </button>
      )}
      <div className="segmented">
        <button className={!certificateMode && tab === 'write' ? 'active' : ''} onClick={() => showTab('write')}>Написать</button>
        <button className={!certificateMode && tab === 'mine' ? 'active' : ''} onClick={() => { showTab('mine'); void mine.refetch() }}>
          Мои обращения{updates.size ? ` · ${updates.size}` : ''}
        </button>
      </div>

      {certificateMode ? <CertificateForm profile={profile} onShowMine={() => showTab('mine')} /> : tab === 'write'
        ? <FeedbackForm profile={profile} onShowMine={() => setTab('mine')} />
        : <MyFeedbackList items={mine.data} loading={mine.isLoading} error={mine.error} onRetry={() => mine.refetch()}
            updates={updates} onMarkSeen={onMarkSeen} />}
    </section>
  )
}

function FeedbackForm({ profile, onShowMine }: { profile: StudentProfile; onShowMine: () => void }) {
  const [kind, setKind] = useState<QuestionKind>('methodist')
  const [text, setText] = useState('')
  const [contact, setContact] = useState('')
  const [consent, setConsent] = useState(false)
  const [website, setWebsite] = useState('')
  const [sent, setSent] = useState<{ id: number; kind_title: string } | null>(null)
  const [formError, setFormError] = useState('')
  const send = useSendFeedback()
  const hasContact = Boolean(contact.trim())
  const hint = KIND_OPTIONS.find((option) => option.kind === kind)?.hint

  /** Почему форму нельзя отправить; пустая строка — можно. */
  const problem = text.trim().length < MIN_TEXT_LENGTH
    ? `Сообщение слишком короткое — напишите хотя бы ${MIN_TEXT_LENGTH} символов.`
    : hasContact && !consent
      ? 'Отметьте согласие на обработку данных или очистите поле «Куда ответить».'
      : ''

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setFormError(problem)
    if (problem) return
    try {
      const result = await send.mutateAsync({
        kind,
        text: text.trim(),
        group_id: profile.group_id,
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
          Адресат: {sent.kind_title}. Ответ появится в разделе «Мои обращения» вашего аккаунта Moodle
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

      <p className="feedback-author">
        <span className="field-label">Отправитель</span>
        <strong>{profile.full_name}</strong>{profile.group_name ? `, ${profile.group_name}` : ''}
        <span className="optional"> — из профиля Moodle</span>
      </p>

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
        Ответ появится во вкладке «Мои обращения». Оставьте email — он придёт и на почту.
      </p>

      {hasContact && (
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

function CertificateForm({ profile, onShowMine }: { profile: StudentProfile; onShowMine: () => void }) {
  const [purpose, setPurpose] = useState('')
  const [copies, setCopies] = useState('')
  const [text, setText] = useState('')
  const [website, setWebsite] = useState('')
  const [orderId, setOrderId] = useState<number | null>(null)
  const send = useSendFeedback()
  const groupName = profile.group_name
  const hasGroup = profile.group_id !== null && Boolean(groupName)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const count = Number(copies)
    if (send.isPending || !hasGroup || !purpose.trim() || !Number.isInteger(count) || count < 1 || count > MAX_CERTIFICATE_COPIES) return
    try {
      const order = await send.mutateAsync({ kind: 'certificate', purpose: purpose.trim(), copies: count, text, website })
      setOrderId(order.id)
    } catch {
      // Ошибка показывается из send.error.
    }
  }

  if (orderId !== null) {
    return (
      <div className="screen-card selection-screen feedback-sent">
        <span className="feedback-sent-icon"><CheckCircle2 size={22} /></span>
        <h1 role="status">Справка заказана · №{orderId}</h1>
        <p className="muted">Следите за статусом и ответом методиста в разделе «Мои обращения».</p>
        <button type="button" className="button button-primary full" onClick={onShowMine}>Мои обращения</button>
      </div>
    )
  }

  return (
    <form className="screen-card selection-screen feedback-form" onSubmit={submit}>
      <h1>Заказать справку</h1>
      <p className="muted">Заказ получит методист. Данные студента взяты из Moodle.</p>
      <dl className="feedback-meta certificate-profile">
        <dt>ФИО</dt><dd>{profile.full_name}</dd>
        <dt>Группа</dt><dd>{groupName ?? 'Не указана'}</dd>
      </dl>
      {!hasGroup && <p className="form-error" role="alert">В профиле Moodle не указана учебная группа.</p>}

      <label className="field-label" htmlFor="certificate-purpose">Для чего нужна справка <span className="optional">— обязательно</span></label>
      <input
        id="certificate-purpose"
        className="text-field"
        required
        pattern={'.*\\S.*'}
        maxLength={4000}
        value={purpose}
        placeholder="Например, для предоставления работодателю"
        onChange={(event) => setPurpose(event.target.value)}
      />

      <label className="field-label" htmlFor="certificate-copies">Количество экземпляров <span className="optional">— обязательно</span></label>
      <input
        id="certificate-copies"
        className="text-field"
        type="number"
        inputMode="numeric"
        required
        min={1}
        max={MAX_CERTIFICATE_COPIES}
        step={1}
        value={copies}
        onChange={(event) => setCopies(event.target.value)}
      />

      <label className="field-label" htmlFor="certificate-text">Дополнительная информация <span className="optional">— необязательно</span></label>
      <textarea
        id="certificate-text"
        className="text-field text-area"
        rows={3}
        maxLength={4000}
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <input
        className="feedback-trap"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        value={website}
        onChange={(event) => setWebsite(event.target.value)}
      />
      {send.error && <p className="form-error" role="alert">{send.error.message}</p>}
      <button className="button button-primary full" type="submit" disabled={send.isPending || !hasGroup}>
        <Send size={16} />{send.isPending ? 'Отправляем…' : 'Отправить заказ'}
      </button>
    </form>
  )
}

function MyFeedbackList({
  items,
  loading,
  error,
  onRetry,
  updates,
  onMarkSeen,
}: {
  items?: MyFeedback[]
  loading: boolean
  error: Error | null
  onRetry: () => void
  updates: ReadonlyMap<number, string>
  onMarkSeen: (item: MyFeedback) => void
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
      {items.map((item) => {
        const update = updates.get(item.id)
        return <article key={item.id} className={`feedback-card${update ? ' unread' : ''}`}>
          <div className="feedback-card-head">
            <div className="feedback-card-meta-row">
              {update && <span className="badge feedback-update-badge">{update}</span>}
              {item.kind === 'certificate'
                ? <span className="badge feedback-certificate-badge">{item.kind_title}</span>
                : <span>{item.kind_title}</span>}
              <time dateTime={item.created_at}>{feedbackDate(item.created_at)}</time>
            </div>
            <span className={`badge feedback-status-${item.status}`}>{STATUS_TITLES[item.status]}</span>
          </div>
          {item.kind === 'certificate' && item.purpose && (
            <dl className="feedback-meta">
              <dt>Для чего</dt><dd>{item.purpose}</dd>
              <dt>Экземпляров</dt><dd>{item.copies}</dd>
            </dl>
          )}
          {item.text && <p className="feedback-text">{item.text}</p>}
          {item.replies.map((reply) => (
            <div key={reply.id} className={`feedback-reply ${reply.author_kind}`}>
              <b>{reply.author_title} · {feedbackDate(reply.created_at)}</b>
              <p className="feedback-text">{reply.text}</p>
            </div>
          ))}
          {update && (
            <button type="button" className="quiet-link feedback-mark-seen" onClick={() => onMarkSeen(item)}>
              <CheckCircle2 size={15} /> Отметить прочитанным
            </button>
          )}
        </article>
      })}
    </div>
  )
}
