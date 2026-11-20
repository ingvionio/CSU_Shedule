import { Download } from 'lucide-react'
import { useEffect, useRef } from 'react'

import { track } from '../api/analytics'

export const ANDROID_APK_URL = '/downloads/raspisanie-iit.apk'

export function AndroidDownload() {
  const downloadLink = useRef<HTMLAnchorElement>(null)
  const attempted = useRef(false)

  useEffect(() => {
    if (attempted.current) return
    attempted.current = true
    track('apk_download')
    downloadLink.current?.click()
  }, [])

  return (
    <main className="android-download">
      <img src="/icons/iit-shield.png" alt="" width={48} height={48} />
      <h1>Расписание ИИТ для Android</h1>
      <p>Загрузка начнётся автоматически. Если она не началась, скачайте APK вручную.</p>
      <a className="button button-primary" href={ANDROID_APK_URL} download ref={downloadLink}>
        Скачать APK <Download size={16} aria-hidden="true" />
      </a>
      <a href="/#/landing">На главную</a>
    </main>
  )
}
