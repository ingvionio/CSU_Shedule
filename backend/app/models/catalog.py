from datetime import date, time

from sqlalchemy import Boolean, CheckConstraint, Date, Integer, SmallInteger, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import WeekParity


class Semester(Base):
    """Учебный семестр. От start_date считаются номера и чётность недель."""

    __tablename__ = "semesters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    # Понедельник первой учебной недели.
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    total_weeks: Mapped[int] = mapped_column(SmallInteger)
    first_week_parity: Mapped[str] = mapped_column(String(8), default=WeekParity.ODD.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint("first_week_parity IN ('odd','even')", name="ck_semesters_first_week_parity"),
        CheckConstraint("total_weeks > 0", name="ck_semesters_total_weeks"),
    )


class Group(Base):
    """Учебная группа. `name` хранится ровно так, как написано в Excel."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    course: Mapped[int] = mapped_column(SmallInteger)
    # Направление подготовки (поток): «ПИ», «ПрИ», «БИ». Заполняется из названия.
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    moodle_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (CheckConstraint("course BETWEEN 1 AND 6", name="ck_groups_course"),)


class TimeSlot(Base):
    """Сетка звонков: номер пары 1-8 и её время."""

    __tablename__ = "time_slots"

    number: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    __table_args__ = (CheckConstraint("number BETWEEN 1 AND 8", name="ck_time_slots_number"),)


class LessonType(Base):
    """Формат пары. Таблица, а не enum — чтобы добавлять форматы без миграции схемы."""

    __tablename__ = "lesson_types"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), unique=True, index=True)


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
