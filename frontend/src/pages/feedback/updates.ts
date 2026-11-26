import { useState } from 'react'

import { readCache, writeCache } from '../../api/cache'
import type { FeedbackStatus, MyFeedback } from '../../api/types'

type SeenFeedback = Record<number, { status: FeedbackStatus; replyId: number }>

function feedbackVersion(item: MyFeedback) {
  const replyId = item.replies.reduce((latest, reply) => (
    reply.author_kind === 'staff' ? Math.max(latest, reply.id) : latest
  ), 0)
  return { status: item.status, replyId }
}

function feedbackUpdate(item: MyFeedback, seen?: SeenFeedback[number]): string | null {
  const current = feedbackVersion(item)
  if (current.replyId > (seen?.replyId ?? 0)) return 'Новый ответ'
  if (current.status !== (seen?.status ?? 'new')) return 'Статус обновлён'
  return null
}

export function useFeedbackUpdates(studentId: number | null, items: MyFeedback[] | undefined) {
  const [local, setLocal] = useState<{ studentId: number; seen: SeenFeedback } | null>(null)
  const key = `feedback-seen:${studentId}`
  const seen = studentId === null ? {} : local?.studentId === studentId ? local.seen : readCache<SeenFeedback>(key) ?? {}
  const updates = new Map<number, string>()
  if (studentId !== null) {
    for (const item of items ?? []) {
      const label = feedbackUpdate(item, seen[item.id])
      if (label) updates.set(item.id, label)
    }
  }

  const markSeen = (item: MyFeedback) => {
    if (studentId === null) return
    const next = writeCache(key, { ...seen, [item.id]: feedbackVersion(item) })
    setLocal({ studentId, seen: next })
  }

  return { updates, markSeen }
}
