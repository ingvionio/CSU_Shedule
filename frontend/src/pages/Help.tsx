import { useState } from 'react'
import { ArrowRight, Search, CircleHelp } from 'lucide-react'
import { helpCategories, helpItems, type HelpCategory } from './helpContent'

export function Help({ onFeedback }: { onFeedback: () => void }) {
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState<HelpCategory | 'Все'>('Все')
  const normalize = (value: string) => value.toLocaleLowerCase('ru').replace(/ё/g, 'е')
  const query = normalize(search.trim())
  const items = helpItems.filter(item => (category === 'Все' || category === item.category) && normalize(`${item.question} ${item.answer}`).includes(query))
  return <section className="help-screen" aria-labelledby="help-title">
    <span className="eyebrow">ПОДСКАЗКИ РЯДОМ</span><h1 id="help-title">Чем помочь?</h1><p className="muted">От первого входа до личной заметки.</p>
    <label className="help-search"><Search size={19} /><span className="sr-only">Поиск по вопросам и ответам</span><input type="search" placeholder="Например, как включить уведомления" value={search} onChange={event => setSearch(event.target.value)} /></label>
    <div className="help-categories" aria-label="Категории помощи">{(['Все', ...helpCategories] as const).map(item => <button key={item} aria-pressed={category === item} className={category === item ? 'selected' : ''} onClick={() => setCategory(item)}>{item}</button>)}</div>
    <p className="help-count" role="status">Найдено ответов: {items.length}</p>
    {helpCategories.map(group => { const entries = items.filter(item => item.category === group); return entries.length > 0 && <section className="faq-category" key={group}><h2>{group}</h2>{entries.map(item => <details className="faq-item" key={item.id}><summary>{item.question}</summary><p>{item.answer}</p></details>)}</section> })}
    {items.length === 0 && <div className="empty-day">Ничего не найдено. Попробуйте другой запрос или категорию.</div>}
    <aside className="help-contact"><CircleHelp size={25} /><div><h2>Не нашли ответ?</h2><p>Напишите нам — поможем разобраться.</p></div><button className="button button-primary" onClick={onFeedback}>Создать обращение <ArrowRight size={16} /></button></aside>
  </section>
}
