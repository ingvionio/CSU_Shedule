import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { useAdminExams, useExamImports, useExamMutations } from '../../api/queries'
import type { ExamEvent, ExamImportReport, ExamInput, ExamKind, Group } from '../../api/types'
import { ExamCard, examDateLabel } from '../exams/ExamCard'

const labels: Record<ExamKind, string> = { session: 'Сессия', retake: 'Пересдачи' }

function ExamForm({ event, groups, busy, onSave, onClose }: {
  event: ExamEvent | null; groups: Group[]; busy: boolean
  onSave: (body: ExamInput) => Promise<void>; onClose: () => void
}) {
  const [form, setForm] = useState<ExamInput>(() => ({
    kind: event?.kind ?? 'session', date: event?.date ?? '', start_time: event?.start_time ?? null,
    subject: event?.subject ?? '', teacher: event?.teacher ?? null, room: event?.room ?? null,
    note: event?.note ?? null, group_ids: event?.groups.map(group => group.id) ?? [],
  }))
  const [error, setError] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try { await onSave(form) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Не удалось сохранить событие') }
  }
  return <div className="modal-backdrop">
    <form className="confirm-modal exam-dialog" role="dialog" aria-modal="true" aria-labelledby="exam-dialog-title" onSubmit={e => void submit(e)}>
      <h2 id="exam-dialog-title">{event ? 'Изменить событие' : 'Добавить событие'}</h2>
      <fieldset disabled={busy} className="exam-fields">
        <label className="admin-field">Вид<select className="select-field" value={form.kind}
          onChange={e => setForm({ ...form, kind: e.target.value as ExamKind })}>
          <option value="session">Сессия</option><option value="retake">Пересдачи</option>
        </select></label>
        <label className="admin-field">Дата<input className="text-field" type="date" required value={form.date} onChange={e => setForm({ ...form, date: e.target.value })} /></label>
        <label className="admin-field">Время<input className="text-field" type="time" value={form.start_time ?? ''} onChange={e => setForm({ ...form, start_time: e.target.value || null })} /></label>
        <label className="admin-field">Дисциплина<input className="text-field" required maxLength={300} value={form.subject} onChange={e => setForm({ ...form, subject: e.target.value })} /></label>
        <label className="admin-field">Преподаватель<input className="text-field" maxLength={200} value={form.teacher ?? ''} onChange={e => setForm({ ...form, teacher: e.target.value || null })} /></label>
        <label className="admin-field">Аудитория<input className="text-field" maxLength={200} value={form.room ?? ''} onChange={e => setForm({ ...form, room: e.target.value || null })} /></label>
        <label className="admin-field">Примечание<textarea className="text-field" value={form.note ?? ''} onChange={e => setForm({ ...form, note: e.target.value || null })} /></label>
        <fieldset className="exam-group-picker"><legend>Группы</legend>
          {groups.map(group => <label key={group.id}><input type="checkbox" checked={form.group_ids.includes(group.id)}
            onChange={e => setForm({ ...form, group_ids: e.target.checked ? [...form.group_ids, group.id] : form.group_ids.filter(id => id !== group.id) })} />{group.name}</label>)}
        </fieldset>
      </fieldset>
      {error && <p className="error-note" role="alert">{error}</p>}
      <div className="exam-actions">
        <button type="submit" className="button button-primary" disabled={busy || !form.group_ids.length}>Сохранить</button>
        <button type="button" className="button button-secondary" disabled={busy} onClick={onClose}>Закрыть</button>
      </div>
    </form>
  </div>
}

function ImportReport({ report }: { report: ExamImportReport }) {
  return <div className="exam-report">
    <h3>{report.applied ? 'Загружено' : 'Результат проверки'}: {report.events_count} событий</h3>
    <div className="import-table-scroll"><table className="import-table"><thead><tr><th>Лист / строка</th><th>Дата / время</th><th>Событие</th><th>Группы</th><th>Аудитория / примечание</th></tr></thead>
      <tbody>{report.rows.map((row, index) => <tr key={index}>
        <td>{row.sheet} / {row.row}</td>
        <td><del>{row.original_date && examDateLabel(row.original_date)}</del> {examDateLabel(row.date)}<br /><del>{row.original_start_time}</del> {row.start_time ?? '—'}</td>
        <td>{row.subject}<small>{row.teacher}</small></td><td>{row.groups.map(group => group.name).join(', ')}</td>
        <td><del>{row.original_room}</del> {row.room}<small>{row.note}</small></td>
      </tr>)}</tbody></table></div>
    <h4>Сопоставление групп</h4>
    <ul>{report.mappings.map(item => <li key={item.short_name}>{item.short_name} → {item.group_name ?? 'не найдена'}</li>)}</ul>
    <h4>Предупреждения ({report.warnings.length})</h4>
    <ul>{report.warnings.map((warning, index) => <li key={index}>
      {warning.sheet}, строка {warning.row}, {warning.column}: {warning.reason} <small>{warning.text}</small>
    </li>)}</ul>
  </div>
}

export function AdminExams({ token, groups, onUnauthorized }: { token: string; groups: Group[]; onUnauthorized: () => void }) {
  const [filters, setFilters] = useState({ kind: '', course: '', group_id: '' })
  const [kind, setKind] = useState<ExamKind>('session')
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<ExamImportReport | null>(null)
  const [editing, setEditing] = useState<ExamEvent | null | undefined>(undefined)
  const [error, setError] = useState('')
  const events = useAdminExams(token, filters)
  const history = useExamImports(token)
  const mutations = useExamMutations(token)
  const busy = Object.values(mutations).some(item => item.isPending)
  useEffect(() => {
    if ([events.error, history.error].some(item => item instanceof ApiError && item.status === 401)) onUnauthorized()
  }, [events.error, history.error, onUnauthorized])
  const failure = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) onUnauthorized()
    setError(error instanceof Error ? error.message : 'Не удалось выполнить действие')
  }
  const action = async (perform: () => Promise<unknown>) => {
    setError('')
    try { await perform() } catch (error) { failure(error) }
  }
  const upload = async (apply: boolean) => {
    if (!file || (apply && (!report || report.applied))) return
    await action(async () => setReport(await mutations.upload.mutateAsync({ file, kind, apply })))
  }
  return <section className="form-screen exam-admin">
    <h1>Сессия и пересдачи</h1>
    <section className="exam-upload">
      <h2>Загрузка Excel</h2>
      <p className="exam-note">Загрузка заменит ранее загруженные события выбранного вида в активном семестре. Ручные события останутся.</p>
      <div className="exam-actions">
        <label className="admin-field">Вид загрузки<select className="select-field" disabled={busy} value={kind} onChange={e => { setKind(e.target.value as ExamKind); setReport(null) }}>
          <option value="session">Сессия</option><option value="retake">Пересдачи</option>
        </select></label>
        <label className="admin-field">Файл .xlsx<input type="file" accept=".xlsx" disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); setReport(null) }} /></label>
      </div>
      <div className="exam-actions">
        <button className="button button-secondary" disabled={busy || !file} onClick={() => void upload(false)}>Проверить</button>
        <button className="button button-primary" disabled={busy || !file || !report || report.applied} onClick={() => void upload(true)}>Применить</button>
      </div>
      {report && <ImportReport report={report} />}
    </section>
    {busy && <p role="status">Сохраняем…</p>}
    {error && <p className="state-note error-note" role="alert">{error}</p>}
    <h2>События</h2>
    <div className="exam-filters">
      <label className="admin-field">Вид<select className="select-field" value={filters.kind} onChange={e => setFilters({ ...filters, kind: e.target.value })}>
        <option value="">Все виды</option><option value="session">Сессия</option><option value="retake">Пересдачи</option>
      </select></label>
      <label className="admin-field">Курс<select className="select-field" value={filters.course} onChange={e => setFilters({ ...filters, course: e.target.value, group_id: '' })}>
        <option value="">Все курсы</option>{[1, 2, 3, 4, 5, 6].map(course => <option key={course} value={course}>{course}</option>)}
      </select></label>
      <label className="admin-field">Группа<select className="select-field" value={filters.group_id} onChange={e => setFilters({ ...filters, group_id: e.target.value })}>
        <option value="">Все группы</option>{groups.filter(group => !filters.course || String(group.course) === filters.course).map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
      </select></label>
      <button className="button button-primary" disabled={busy} onClick={() => setEditing(null)}>Добавить</button>
    </div>
    {events.isPending && <p>Загружаем события…</p>}
    {events.isError && <p className="state-note error-note">{events.error.message}<button className="button button-secondary" onClick={() => void events.refetch()}>Повторить</button></p>}
    {events.data?.length === 0 && <p className="empty-day">Событий нет</p>}
    {events.data?.map(event => <ExamCard key={event.id} event={event} original={event} cancelled={event.cancelled}>
      <p>{examDateLabel(event.date)} · {labels[event.kind]}</p>
      <p className="muted">{event.groups.map(group => group.name).join(', ')} · {event.source === 'manual' ? 'Вручную' : 'Загрузка № ' + event.import_id}</p>
      <div className="exam-actions">
        <button className="button button-secondary" disabled={busy} onClick={() => setEditing(event)}>Изменить</button>
        <button className="button button-secondary" disabled={busy} onClick={() => void action(() => mutations.cancel.mutateAsync({ id: event.id, cancelled: !event.cancelled }))}>{event.cancelled ? 'Вернуть' : 'Отменить'}</button>
        <button className="button button-secondary" disabled={busy} onClick={() => void action(() => mutations.remove.mutateAsync(event.id))}>Удалить</button>
      </div>
    </ExamCard>)}
    <h2>История загрузок</h2>
    {history.isPending && <p>Загружаем историю…</p>}
    {history.isError && <p className="state-note error-note">{history.error.message}<button className="button button-secondary" onClick={() => void history.refetch()}>Повторить</button></p>}
    {history.data?.length === 0 && <p className="muted">Загрузок пока нет</p>}
    {history.data?.map(item => <details key={item.id} className="exam-history">
      <summary>№ {item.id} · {item.file_name} · {labels[item.kind]} · {item.events_count} событий</summary>
      <p>{new Date(item.uploaded_at).toLocaleString('ru-RU')} · {item.uploaded_by} · семестр № {item.semester_id}</p>
      <ul>{item.warnings.map((warning, index) => <li key={index}>{warning.sheet}, {warning.row}{warning.column}: {warning.reason}</li>)}</ul>
    </details>)}
    {editing !== undefined && <ExamForm key={editing?.id ?? 'new'} event={editing} groups={groups} busy={busy} onClose={() => setEditing(undefined)} onSave={async body => {
      try {
        if (editing) await mutations.patch.mutateAsync({ id: editing.id, body })
        else await mutations.create.mutateAsync(body)
        setEditing(undefined)
      } catch (error) { failure(error); throw error }
    }} />}
  </section>
}
