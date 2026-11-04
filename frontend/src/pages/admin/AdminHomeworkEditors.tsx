import { useState } from 'react'
import { UserPlus, X } from 'lucide-react'

import { useHomeworkEditorMutations, useHomeworkEditors, useStudents } from '../../api/queries'
import type { Group } from '../../types'

export function AdminHomeworkEditors({ token, groups, groupId, onGroupChange }: { token: string; groups: Group[]; groupId: number | null; onGroupChange: (id: number) => void }) {
  const editors = useHomeworkEditors(token, groupId)
  const students = useStudents(token, { group_id: groupId ?? undefined }, groupId !== null)
  const mutations = useHomeworkEditorMutations(token, groupId ?? 0)
  const [selected, setSelected] = useState('')
  const group = groups.find((item) => item.id === groupId)
  const assigned = new Set((editors.data ?? []).map((item) => item.user_id))
  const available = (students.data ?? []).filter((student) => !assigned.has(student.id))

  return <section className="screen-card admin-homework-editors">
    <span className="eyebrow">ГРУППОВАЯ ДОМАШКА</span>
    <h1>Редакторы группы</h1>
    <p className="muted">Назначьте старосту и заместителя. Они смогут публиковать домашку для выбранной группы.</p>
    <label className="admin-field"><span>Группа</span><select className="select-field" value={groupId ?? ''} onChange={(event) => onGroupChange(Number(event.target.value))}>{groups.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    {group && <>
      <div className="admin-editor-add"><select className="select-field" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Выберите студента</option>{available.map((student) => <option key={student.id} value={student.id}>{student.full_name} · профиль №{student.id}</option>)}</select><button className="button button-primary" disabled={!selected || mutations.assign.isPending} onClick={async () => { await mutations.assign.mutateAsync({ userId: Number(selected), isPrimary: (editors.data ?? []).length === 0 }); setSelected('') }}><UserPlus size={16} />Назначить</button></div>
      <div className="editor-list">{(editors.data ?? []).map((editor) => <div className="editor-row" key={editor.user_id}><span><strong>{editor.full_name} · №{editor.user_id}</strong>{editor.is_primary && <small>Основной редактор</small>}</span><button className="icon-button outlined" aria-label={`Отозвать ${editor.full_name}`} onClick={() => mutations.remove.mutate(editor.user_id)}><X size={16} /></button></div>)}</div>
    </>}
  </section>
}
