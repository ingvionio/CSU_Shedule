"""Консольные команды бэкенда.

    python -m app.cli init-db                      # создать таблицы (без Alembic)
    python -m app.cli seed-semester                # завести активный семестр и справочники
    python -m app.cli import-excel <путь к .xlsx>  # разобрать файл и залить расписание
    python -m app.cli stats                        # что лежит в базе
    python -m app.cli send-emails                  # дослать неотправленные письма
    python -m app.cli send-emails --test <email>   # проверить настройки почты
    python -m app.cli generate-vapid               # ключи для push-уведомлений
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


def import_weekly(paths: list[str], skip_errors: bool = False) -> int:
    from app.services.weekly_importer import import_weekly as import_batch

    with SessionLocal() as session:
        semester = session.scalar(select(Semester).where(Semester.is_active.is_(True)))
        if semester is None:
            print("Нет активного семестра. Сначала: python -m app.cli seed-semester")
            return 1
        report = import_batch(session, paths, semester, skip_errors=skip_errors)
        if report.errors and not skip_errors:
            session.rollback()
        else:
            session.commit()
        for file in report.files:
            parsed = file.parsed
            if not parsed.errors:
                print(f"{parsed.group_name}, неделя {parsed.week_number}: пар {len(parsed.lessons)}")
        for issue in report.errors + report.warnings:
            label = "Ошибка" if issue["severity"] == "error" else "Предупреждение"
            print(f"{label}: {issue['file_name']} {issue['sheet']}!{issue['cell']}: {issue['reason']} — {issue['text']}")
        if report.errors and not skip_errors:
            print("Импорт отменён: ничего не записано.")
        print(f"Файлов: {len(report.files)}, групп: {report.groups_count} (новых: {report.groups_created}), "
              f"пар: {report.lessons_created}, удалено изменений: {report.overrides_deleted}, ошибок: {len(report.errors)}")
        return 1 if report.errors else 0


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


def generate_vapid() -> None:
    """Ключи для Web Push: публичный отдаётся браузеру, приватный остаётся на сервере."""
    import base64

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from py_vapid import Vapid

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    vapid = Vapid()
    vapid.generate_keys()
    public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    print("Добавьте в .env в корне репозитория:\n")
    print(f"VAPID_PUBLIC_KEY={b64(public)}")
    print(f"VAPID_PRIVATE_KEY={b64(private)}")
    print("VAPID_SUBJECT=mailto:<почта для связи>")


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

    weekly = sub.add_parser("import-weekly", help="загрузить понедельное расписание из файлов, папок или архивов")
    weekly.add_argument("paths", nargs="+")
    weekly.add_argument("--skip-errors", action="store_true", help="пропустить ошибочные файлы")

    sub.add_parser("stats", help="показать содержимое базы")

    mail = sub.add_parser("send-emails", help="дослать письма из очереди")
    mail.add_argument("--test", metavar="EMAIL", help="отправить проверочное письмо")

    sub.add_parser("generate-vapid", help="сгенерировать ключи для push-уведомлений")

    args = parser.parse_args()

    if args.command == "init-db":
        init_db()
    elif args.command == "seed-semester":
        seed_semester(args.title, date.fromisoformat(args.start), args.weeks, args.parity)
    elif args.command == "import-excel":
        import_excel(args.path)
    elif args.command == "import-weekly":
        sys.exit(import_weekly(args.paths, args.skip_errors))
    elif args.command == "stats":
        stats()
    elif args.command == "send-emails":
        send_emails(args.test)
    elif args.command == "generate-vapid":
        generate_vapid()


if __name__ == "__main__":
    main()
