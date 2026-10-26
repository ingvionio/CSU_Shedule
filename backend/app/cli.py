"""Консольные команды бэкенда.

    python -m app.cli init-db                      # создать таблицы (без Alembic)
    python -m app.cli seed-semester                # завести активный семестр и справочники
    python -m app.cli import-excel <путь к .xlsx>  # разобрать файл и залить расписание
    python -m app.cli stats                        # что лежит в базе
    python -m app.cli send-emails                  # дослать неотправленные письма
    python -m app.cli send-emails --test <email>   # проверить настройки почты
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from sqlalchemy import func, select

from app.core.db import SessionLocal, engine
from app.models import Base, Group, Lesson, Room, Semester, Subject, Teacher, WeekParity
from app.services.importer import ensure_reference_data, import_workbook

# Семестр по умолчанию: 1 семестр 2026/27, начало 1 сентября 2026 (вторник),
# первая учебная неделя — нечётная.
DEFAULT_SEMESTER = {
    "title": "1 семестр 2026/27",
    "start_date": date(2026, 9, 1),
    "total_weeks": 18,
    "first_week_parity": WeekParity.ODD.value,
}


def init_db() -> None:
    Base.metadata.create_all(engine)
    print(f"Таблицы созданы: {len(Base.metadata.tables)}")


def seed_semester(
    title: str,
    start: date,
    total_weeks: int,
    parity: str,
) -> int:
    """Создаёт (или обновляет) активный семестр и справочники."""
    first_monday = start - timedelta(days=start.weekday())
    end_date = first_monday + timedelta(weeks=total_weeks) - timedelta(days=1)

    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.title == title))
        if semester is None:
            semester = Semester(title=title)
            session.add(semester)

        semester.start_date = start
        semester.end_date = end_date
        semester.total_weeks = total_weeks
        semester.first_week_parity = parity
        semester.is_active = True
        session.flush()

        # Активным может быть только один семестр.
        for other in session.scalars(select(Semester).where(Semester.id != semester.id)).all():
            other.is_active = False

        ensure_reference_data(session)
        session.commit()

        print(
            f"Семестр #{semester.id} «{semester.title}»: "
            f"нед. 1 = {first_monday}, всего {total_weeks} нед., конец {end_date}, "
            f"первая неделя {parity}"
        )
        return semester.id


def import_excel(path: str) -> None:
    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        if semester is None:
            sys.exit("Нет активного семестра. Сначала: python -m app.cli seed-semester")

        report = import_workbook(session, path, semester, file_name=path.rsplit("/", 1)[-1])
        print(
            f"Импорт #{report.import_id} в «{report.semester_title}»: "
            f"групп создано {report.groups_created}, пар записано {report.lessons_created}, "
            f"предупреждений {report.warnings}"
        )


def stats() -> None:
    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        print(f"Активный семестр: {semester.title if semester else '—'}")
        for model, label in ((Group, "групп"), (Lesson, "пар"), (Subject, "предметов"), (Teacher, "преподавателей"), (Room, "аудиторий")):
            print(f"  {label}: {session.scalar(select(func.count()).select_from(model))}")

        rows = session.execute(
            select(Group.name, Group.course, func.count(Lesson.id))
            .outerjoin(Lesson, Lesson.group_id == Group.id)
            .group_by(Group.id)
            .order_by(Group.course, Group.name)
        ).all()
        print("\n  группа            курс  пар")
        for name, course, count in rows:
            print(f"  {name:18}{course:^6}{count:4}")


def send_emails(test_to: str | None) -> None:
    from app.models import EmailOutbox, EmailStatus
    from app.services.mailer import deliver, deliver_pending

    with SessionLocal() as session:
        if test_to:
            item = EmailOutbox(
                to_address=test_to,
                subject="Проверка почты расписания",
                body="Если вы читаете это письмо, отправка обращений настроена.",
            )
            session.add(item)
            session.commit()
            deliver(session, [item])
            if item.status != EmailStatus.SENT.value:
                sys.exit(f"Не отправлено ({item.status}): {item.last_error or 'SMTP_USER не задан'}")
            print(f"Отправлено на {test_to}")
            return

        print(f"Попыток отправки: {deliver_pending(session)}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli", description="Команды бэкенда расписания")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать таблицы по моделям")

    seed = sub.add_parser("seed-semester", help="завести активный семестр и справочники")
    seed.add_argument("--title", default=DEFAULT_SEMESTER["title"])
    seed.add_argument("--start", default=DEFAULT_SEMESTER["start_date"].isoformat(), help="ГГГГ-ММ-ДД")
    seed.add_argument("--weeks", type=int, default=DEFAULT_SEMESTER["total_weeks"])
    seed.add_argument("--parity", choices=["odd", "even"], default=DEFAULT_SEMESTER["first_week_parity"])

    imp = sub.add_parser("import-excel", help="разобрать Excel и залить расписание")
    imp.add_argument("path")

    sub.add_parser("stats", help="показать содержимое базы")

    mail = sub.add_parser("send-emails", help="дослать письма из очереди")
    mail.add_argument("--test", metavar="EMAIL", help="отправить проверочное письмо")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "seed-semester":
        seed_semester(args.title, date.fromisoformat(args.start), args.weeks, args.parity)
    elif args.command == "import-excel":
        import_excel(args.path)
    elif args.command == "stats":
        stats()
    elif args.command == "send-emails":
        send_emails(args.test)


if __name__ == "__main__":
    main()
