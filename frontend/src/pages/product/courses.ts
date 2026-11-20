import type { ProductSummary } from '../../api/types'

type GroupRow = ProductSummary['groups'][number]

/** Группы по курсам: сначала курсы бакалавриата, затем магистратуры; у курса — сумма по его группам. */
export function coursesOf(groups: GroupRow[]) {
  const courses = new Map<string, { key: string; title: string; order: number; groups: GroupRow[]; users: number; new: number; active: number }>()
  for (const group of groups) {
    const master = group.level === 'master'
    const key = `${group.level}-${group.course}`
    const course = courses.get(key) ?? {
      key,
      title: master ? `${group.course} курс магистратуры` : `${group.course} курс`,
      order: (master ? 100 : 0) + group.course,
      groups: [], users: 0, new: 0, active: 0,
    }
    course.groups.push(group)
    course.users += group.users
    course.new += group.new
    course.active += group.active
    courses.set(key, course)
  }
  return Array.from(courses.values()).sort((a, b) => a.order - b.order)
}
