import { useEffect, useRef, useState } from 'react'
import { Check, FileSpreadsheet, RefreshCw, Upload, X } from 'lucide-react'

import { ApiError } from '../../api/client'
import { useImportMutations, useImports } from '../../api/queries'
import type { ImportIssue, SemesterImportReport, WeeklyImportReport } from '../../api/types'

type Mode = 'weekly' | 'semester'
type Result = { kind: 'weekly'; report: WeeklyImportReport } | { kind: 'semester'; report: SemesterImportReport }

function Issues({ issues }: { issues: ImportIssue[] }) {
  return <ul className="import-issues">{issues.map((issue, index) => (
    <li key={index}>
      {[issue.sheet, issue.cell].filter(Boolean).join('!')}{issue.cell || issue.sheet ? ': ' : ''}{issue.reason}
      {issue.text && <span>«{issue.text}»</span>}
    </li>
  ))}</ul>
}

function Report({ result }: { result: Result }) {
  const report = result.report
  return <div className="import-report" aria-live="polite">
    <h2>{report.applied ? 'Результат загрузки' : 'Результат проверки'}</h2>
    {report.applied && <p className="success-note"><Check size={16} />Расписание загружено</p>}
    <div className="import-table-scroll">
      {result.kind === 'weekly' ? <table className="import-table">
        <caption className="muted">Книги понедельного расписания</caption>
        <thead><tr><th>Файл / группа</th><th>Неделя (даты)</th><th>Пар</th><th>Статус</th></tr></thead>
        <tbody>{result.report.files.map((file, index) => <tr key={index}>
          <td><strong>{file.group_name ?? 'Группа не определена'}</strong><small>{file.file_name}</small></td>
          <td>{file.week_number ?? '—'}{file.parity && ` · ${file.parity === 'odd' ? 'нечётная' : 'чётная'}`}<small>{file.start_date ?? '—'} — {file.end_date ?? '—'}</small></td>
          <td>{file.lessons_count}</td>
          <td>
            <span>{file.errors.length ? 'Ошибка' : file.warnings.length ? 'Предупреждения' : '✓'}</span>
            <Issues issues={file.errors} /><Issues issues={file.warnings} />
          </td>
        </tr>)}</tbody>
      </table> : <table className="import-table">
        <caption className="muted">{result.report.file_name}</caption>
        <thead><tr><th>Группа</th><th>Пар</th></tr></thead>
        <tbody>{result.report.groups.map((group) => <tr key={group.name}><td>{group.name}</td><td>{group.lessons_count}</td></tr>)}</tbody>
      </table>}
    </div>
    {result.kind === 'weekly' ? <p className="muted">
      Файлов: {result.report.files_count}, групп: {result.report.groups_count} (новых: {report.groups_created}),
      пар: {report.lessons_created}, временных изменений {report.applied ? 'удалено' : 'удалится'}: {report.overrides_deleted},
      ошибок: {result.report.errors_count}, предупреждений: {result.report.warnings_count}.
    </p> : <>
      <Issues issues={result.report.errors} />
      {result.report.warnings.length > 0 && <div><strong>Предупреждения</strong><Issues issues={result.report.warnings} /></div>}
      <p className="muted">
        Пар: {report.lessons_created}, новых групп: {report.groups_created}.
        {report.applied ? 'Заменено' : 'Будет заменено'} пар: {result.report.lessons_replaced},
        временных изменений {report.applied ? 'удалено' : 'удалится'}: {report.overrides_deleted}.
      </p>
    </>}
    {result.kind === 'semester' && !report.applied && result.report.homework_affected > 0 && <p className="muted">
      Домашка у заменяемых пар: {result.report.homework_affected} — будет перепривязана к тем же парам, где они совпадут
    </p>}
    {report.homework_rebound + report.homework_unbound > 0 && <p className="muted">
      Домашка: {report.applied ? 'перепривязано' : 'будет перепривязано'} {report.homework_rebound},
      {' '}{report.applied ? 'отвязано' : 'будет отвязано'} {report.homework_unbound}.
    </p>}
    {report.homework_unbound > 0 && <p className="state-note import-homework-warning" role="alert">
      {report.homework_unbound} заданий останутся без пары — они видны в «Заданиях на неделю», но не в окне пары
    </p>}
  </div>
}

export function AdminImports({ token, onUnauthorized }: { token: string; onUnauthorized: () => void }) {
  const [mode, setMode] = useState<Mode>('weekly')
  const [files, setFiles] = useState<File[]>([])
  const [skipErrors, setSkipErrors] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [checked, setChecked] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const history = useImports(token)
  const mutations = useImportMutations(token)
  const busy = mutations.weekly.isPending || mutations.semester.isPending
  const canUpload = checked && result !== null && !result.report.applied && (
    result.kind === 'weekly'
      ? result.report.errors_count === 0 || (skipErrors && result.report.files.some((file) => !file.errors.length))
      : result.report.errors.length === 0
  )

  useEffect(() => {
    if (history.error instanceof ApiError && history.error.status === 401) onUnauthorized()
  }, [history.error, onUnauthorized])

  const resetCheck = () => { setResult(null); setChecked(false); setError('') }
  const changeMode = (next: Mode) => {
    setMode(next); setFiles([]); setSkipErrors(false); resetCheck()
    if (input.current) input.current.value = ''
  }
  const selectFiles = (selected: File[]) => {
    if (busy) return
    if (mode === 'semester' && selected.length > 1) {
      resetCheck(); setError('Для расписания семестра выберите один файл .xlsx'); return
    }
    setFiles(mode === 'weekly' ? [...files, ...selected] : selected)
    resetCheck()
  }
  const run = async (dryRun: boolean) => {
    if (busy || !files.length || (!dryRun && !canUpload)) return
    if (!dryRun && result?.kind === 'semester' && !window.confirm(
      `Будут заменены пары групп: ${result.report.groups.map((group) => group.name).join(', ')} ` +
      `(${result.report.lessons_replaced} пар, ${result.report.overrides_deleted} временных изменений удалится)`,
    )) return
    setError(''); setChecked(false)
    try {
      const next: Result = mode === 'weekly'
        ? { kind: 'weekly', report: await mutations.weekly.mutateAsync({ files, dryRun, skipErrors }) }
        : { kind: 'semester', report: await mutations.semester.mutateAsync({ file: files[0], dryRun }) }
      setResult(next); setChecked(dryRun)
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) onUnauthorized()
      setError(failure instanceof Error ? failure.message : 'Не удалось загрузить расписание')
    }
  }

  return <section className="form-screen import-screen">
    <div className="screen-heading"><span className="eyebrow">АДМИНИСТРИРОВАНИЕ</span><h1>Загрузка расписаний</h1>
      <p className="muted">Выберите файлы и проверьте результат перед загрузкой.</p>
    </div>
    <div className="admin-target-tabs" aria-label="Вид расписания">
      <button disabled={busy} className={mode === 'weekly' ? 'active' : ''} onClick={() => changeMode('weekly')}>Магистры — по неделям</button>
      <button disabled={busy} className={mode === 'semester' ? 'active' : ''} onClick={() => changeMode('semester')}>Бакалавры — семестр</button>
    </div>
    <div className="upload-area" onDragOver={(event) => event.preventDefault()} onDrop={(event) => {
      event.preventDefault(); selectFiles(Array.from(event.dataTransfer.files))
    }} aria-busy={busy}>
      <div className="upload-icon"><FileSpreadsheet size={22} /></div>
      <strong>Перетащите {mode === 'weekly' ? 'файлы .xlsx или .zip' : 'файл .xlsx'} сюда</strong>
      <span>До 20 МБ на файл, до 50 МБ всего</span>
      <button className="button button-secondary upload-button" disabled={busy} onClick={() => input.current?.click()}>
        <Upload size={16} />{mode === 'weekly' ? 'Выбрать файлы' : 'Выбрать файл'}
      </button>
      <input ref={input} className="import-file-input" type="file" aria-label="Файлы расписания" disabled={busy}
        multiple={mode === 'weekly'} accept={mode === 'weekly' ? '.xlsx,.zip' : '.xlsx'}
        onChange={(event) => { selectFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} />
    </div>
    <ul className="import-files">{files.map((file, index) => <li key={index}>
      <span><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} МБ</small></span>
      <button className="icon-button" disabled={busy} aria-label={`Убрать ${file.name}`} onClick={() => {
        setFiles(files.filter((_, position) => position !== index)); resetCheck()
      }}><X size={16} /></button>
    </li>)}</ul>
    {mode === 'weekly' && <label className="import-skip"><input type="checkbox" checked={skipErrors} disabled={busy}
      onChange={(event) => { setSkipErrors(event.target.checked); resetCheck() }} />Пропустить файлы с ошибками</label>}
    {error && <div className="state-note error-note" role="alert">{error}</div>}
    <div className="import-actions">
      <button className="button button-secondary" disabled={busy || !files.length} onClick={() => void run(true)}>Проверить</button>
      <button className="button button-primary" disabled={busy || !canUpload} onClick={() => void run(false)}><Upload size={16} />Загрузить</button>
    </div>
    {busy && <p className="state-note" role="status">Обрабатываем файлы…</p>}
    {!checked && files.length > 0 && !busy && !result?.report.applied && <p className="muted">Для загрузки сначала проверьте выбранные файлы.</p>}
    {result && <Report result={result} />}
    <div className="import-history"><h2>Последние загрузки</h2>
      {history.isLoading && <p className="muted">Загружаем историю…</p>}
      {history.isError && <div className="state-note error-note"><span>{history.error.message}</span>
        <button className="button button-secondary" onClick={() => void history.refetch()}><RefreshCw size={16} />Повторить</button>
      </div>}
      {history.data?.length === 0 && <p className="muted">Загрузок пока нет.</p>}
      {history.data && history.data.length > 0 && <div className="import-table-scroll"><table className="import-table">
        <thead><tr><th>Файл / дата</th><th>Кто / статус</th><th>Пар</th><th>Ошибки / предупреждения</th></tr></thead>
        <tbody>{history.data.map((item) => <tr key={item.id}>
          <td>{item.file_name}<small>№ {item.id} · {new Date(item.uploaded_at).toLocaleString('ru-RU')}</small></td>
          <td>{item.uploaded_by ?? '—'}<small>{({ published: 'Загружено', parsed: 'Разобрано', failed: 'Ошибка' })[item.status] ?? item.status}</small></td>
          <td>{item.lessons_count}</td><td>{item.errors_count} / {item.warnings_count}</td>
        </tr>)}</tbody>
      </table></div>}
    </div>
  </section>
}
