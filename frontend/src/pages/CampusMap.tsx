import { useEffect, useState } from 'react'
import { ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react'

const MAP_URL = 'https://map.csu.ru/'

/** Отдельный экран оставляет всё нижнее пространство навигации самой карты. */
export function CampusMap({ active, onBack }: { active: boolean; onBack: () => void }) {
  const [opened, setOpened] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [slow, setSlow] = useState(false)
  const [online, setOnline] = useState(() => navigator.onLine)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (active) setOpened(true)
  }, [active])

  useEffect(() => {
    const connected = () => {
      setOnline(true)
      setLoaded(false)
      setAttempt((value) => value + 1)
    }
    const disconnected = () => setOnline(false)
    window.addEventListener('online', connected)
    window.addEventListener('offline', disconnected)
    return () => {
      window.removeEventListener('online', connected)
      window.removeEventListener('offline', disconnected)
    }
  }, [])

  useEffect(() => {
    if ((!opened && !active) || loaded || !online) return
    const timer = window.setTimeout(() => setSlow(true), 12000)
    return () => window.clearTimeout(timer)
  }, [opened, active, loaded, online, attempt])

  const retry = () => {
    setLoaded(false)
    setSlow(false)
    setAttempt((value) => value + 1)
  }

  if (!opened && !active) return null

  return (
    <section className="campus-map" hidden={!active} aria-label="Карта университета">
      <header className="campus-map-header">
        <button className="icon-button" onClick={onBack} aria-label="Вернуться к расписанию" title="Вернуться к расписанию">
          <ArrowLeft size={20} />
        </button>
        <strong>Карта ЧелГУ</strong>
        <a className="icon-button" href={MAP_URL} target="_blank" rel="noopener noreferrer"
          aria-label="Открыть карту в отдельной вкладке" title="Открыть в отдельной вкладке">
          <ExternalLink size={18} />
        </a>
      </header>
      <div className="campus-map-body">
        {online && <iframe
          key={attempt}
          className="campus-map-frame"
          src={MAP_URL}
          title="Навигатор по университету ЧелГУ"
          referrerPolicy="no-referrer"
          onLoad={() => { setLoaded(true); setSlow(false) }}
        />}
        {(!online || !loaded) && <div className="campus-map-status" role="status">
          <strong>{!online ? 'Для карты нужен интернет' : slow ? 'Карта загружается дольше обычного' : 'Загружаем карту…'}</strong>
          {(!online || slow) && <>
            <p>Поиск аудиторий и маршруты доступны при подключении к сайту карты.</p>
            <button className="button button-secondary" onClick={retry}><RefreshCw size={16} />Повторить</button>
            <a className="quiet-link" href={MAP_URL} target="_blank" rel="noopener noreferrer">Открыть карту отдельно <ExternalLink size={14} /></a>
          </>}
        </div>}
      </div>
    </section>
  )
}
