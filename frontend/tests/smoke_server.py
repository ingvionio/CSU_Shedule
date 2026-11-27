"""Local UI smoke fixture. No Moodle requests, real accounts or database writes.
Run after npm run build: python tests/smoke_server.py.
Student login: fixture / fixture; admin login: admin / fixture.
This server deliberately uses mock data and binds only to 127.0.0.1:4175.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from os import environ
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json

DIST = Path(__file__).resolve().parents[1] / 'dist'
ACTIVE_DIST = Path(environ['SMOKE_PREVIOUS_DIST']).resolve() if environ.get('SMOKE_PREVIOUS_DIST') else DIST
WORKER_REVISION = 0
GROUP = {'id': 1, 'name': 'ТЕСТ ПИ 101', 'course': 1, 'direction': 'ПИ', 'level': 'bachelor'}
PROFILE = {'id': 1, 'full_name': 'Тестовый студент', 'group_id': 1, 'group_name': GROUP['name'], 'moodle_username': 'fixture'}
WEEK = {'number': 11, 'parity': 'odd', 'start_date': '2026-11-09', 'end_date': '2026-11-14', 'is_current': True, 'prev': 10, 'next': 12}
LESSON = {'id': 'l-1', 'note_key': 'fixture-note', 'start_time': '09:00', 'end_time': '10:30', 'slot': 1, 'subject': 'Тестовое занятие', 'type': {'code': 'lecture', 'name': 'Лекция'}, 'room': '331', 'teacher': 'Тестовый преподаватель', 'subgroup': None, 'status': 'regular', 'change': None}
DATE = '2026-11-09'
STAMP = DATE + 'T09:00:00Z'
SLOTS = [{'number': i + 1, 'start_time': start, 'end_time': end} for i, (start, end) in enumerate(
    [('09:00', '10:30'), ('10:40', '12:10'), ('12:30', '14:00'), ('14:10', '15:40'), ('15:50', '17:20'), ('17:30', '19:00')])]
MOVE = {'date': DATE, 'slot': 5, 'start_time': '15:50', 'end_time': '17:20'}
LESSONS = [LESSON, *[
    {**LESSON, 'id': f'l-{i + 1}', 'note_key': None, 'start_time': SLOTS[i]['start_time'], 'end_time': SLOTS[i]['end_time'],
     'slot': i + 1, 'subject': subject, 'status': status,
     'change': {'override_id': i, 'kind': kind, 'comment': 'Комментарий к изменению', 'original': original,
                'moved_from': None, 'moved_to': MOVE if kind == 'move' else None}}
    for i, (subject, status, kind, original) in enumerate([
        ('Алгоритмы и структуры данных', 'changed', 'replace', {'room': '329'}),
        ('ДлинноеНазваниеДляПроверкиПереносаТекста', 'cancelled', 'cancel', None),
        ('Проектная практика', 'moved_out', 'move', None),
    ], start=1)
], {**LESSON, 'id': 'l-5', 'note_key': None, 'start_time': MOVE['start_time'], 'end_time': MOVE['end_time'], 'slot': 5,
    'subject': 'Проектная практика', 'status': 'moved_in',
    'change': {'override_id': 3, 'kind': 'move', 'comment': None, 'original': None,
               'moved_from': {'date': DATE, 'slot': 4, 'start_time': '14:10', 'end_time': '15:40'}, 'moved_to': None}},
   {**LESSON, 'id': 'e-1', 'note_key': None, 'start_time': '17:30', 'end_time': None, 'slot': 6,
    'subject': 'Дискретная математика', 'type': {'code': 'exam', 'name': 'Экзамен'},
    'event': {'kind': 'session', 'note': 'Возьмите зачётную книжку.', 'groups': [GROUP['name']]}}]
SCHEDULE = {'group': GROUP, 'week': WEEK, 'generated_at': STAMP, 'days': [
    {'date': f'2026-11-{9+i:02}', 'weekday': i+1, 'is_today': i == 0, 'lessons': LESSONS if i == 0 else []} for i in range(6)]}
MESSAGE = {'id': 12, 'title': 'Тестовое важное сообщение', 'body': 'Проверка открытия из push-ссылки и подтверждения.', 'importance': 'high', 'sent_at': '2026-11-09T09:00:00Z', 'read_at': None, 'acknowledged_at': None, 'requires_ack': True, 'is_unread': True}
HOMEWORK = {'id': 1, 'group_id': 1, 'lesson_id': 1, 'lesson_date': '2026-11-09', 'subject': LESSON['subject'], 'title': 'Тестовое задание', 'body': 'Прочитать условие.', 'due_date': '2026-11-10', 'source': 'from_class', 'status': 'published', 'version': 1, 'created_by': 1, 'created_by_name': 'Редактор группы', 'updated_by': 1, 'updated_by_name': 'Редактор группы', 'created_at': '2026-11-09T09:00:00Z', 'updated_at': '2026-11-09T09:00:00Z', 'completed_by_me': False}
NOTES = [{'id': 1, 'occurrence_key': 'fixture-note', 'group_id': 1, 'lesson_date': DATE, 'subject': LESSON['subject'],
          'body': 'Проверить примеры перед следующей парой.', 'version': 1, 'updated_at': STAMP}]
FEEDBACK = [{'id': 1, 'kind': 'certificate', 'kind_title': 'Справка об обучении', 'text': 'Справка для учебной практики.',
             'purpose': 'Для учебной практики', 'copies': 2, 'status': 'answered', 'created_at': STAMP,
             'replies': [{'id': 1, 'author_kind': 'staff', 'author_title': 'Деканат', 'text': 'Справка готова.', 'created_at': STAMP}]}]
EXAMS = [{'id': 1, 'semester_id': 1, 'kind': 'session', 'event_type': 'exam', 'date': DATE, 'start_time': '17:30',
          'subject': 'Дискретная математика', 'teacher': LESSON['teacher'], 'room': '331', 'note': 'Возьмите зачётную книжку.',
          'original': {'room': '329'}, 'groups': [GROUP], 'cancelled': False, 'source': 'manual', 'import_id': None,
          'created_at': STAMP, 'updated_at': STAMP}]
PRODUCT_USER = {'id': 1, 'full_name': PROFILE['full_name'], 'group': GROUP, 'created_at': STAMP,
                'last_seen_at': STAMP, 'active_days_30': 5, 'last_platform': 'web'}
STUDENT_TOKEN = {'access_token': 'test-only-token', 'token_type': 'bearer', 'expires_at': '2099-01-01T00:00:00Z', 'profile': PROFILE}
ADMIN_TOKEN = {'access_token': 'test-only-admin-token', 'token_type': 'bearer', 'expires_at': '2099-01-01T00:00:00Z'}

def product_summary(query):
    start, end = (parse_qs(query)[key][0] for key in ('start', 'end'))
    return {
        'start_date': start, 'end_date': end, 'days': 2, 'users_total': 32, 'users_new': 4, 'active_users': 18,
        'dau': 8, 'wau': 14, 'mau': 18, 'users_with_push': 9, 'tracking_since': DATE,
        'funnel': {'landing_view': 32, 'login_click': 23, 'login_submit': 20, 'login_success': 18,
                   'login_any': 18, 'login_without_landing': 2},
        'login_failures': {'auth': 2, 'group': 0, 'other': 0}, 'apk_downloads': 8, 'apk_installs': 6, 'apk_installs_total': 9,
        'by_platform': {'web': 10, 'apk': 6, 'pwa': 2}, 'features': [{'name': 'schedule_view', 'events': 42, 'users': 18}],
        'retention': [{'week': 1, 'eligible': 16, 'returned': 11}], 'groups': [{**GROUP, 'users': 32, 'new': 4, 'active': 18}],
        'daily': [{'date': date, 'dau': count, 'new_users': 2, 'landing_devices': 16, 'login_success': 9}
                  for date, count in ((start, 6), (end, 8))],
    }

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ACTIVE_DIST), **kwargs)

    def respond(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "frame-src https://map.csu.ru; object-src 'none'; base-uri 'self'; form-action 'self'")
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path.removeprefix('/api/v1')
        if not self.path.startswith('/api/'):
            if url.path == '/sw.js':
                del self.headers['If-Modified-Since']
                if WORKER_REVISION:
                    worker = (DIST / 'sw.js').read_bytes() + f'\n/* fixture {WORKER_REVISION} */\n'.encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/javascript')
                    self.send_header('Content-Length', str(len(worker)))
                    self.end_headers()
                    self.wfile.write(worker)
                    return
            return super().do_GET()
        if path == '/product/summary':
            return self.respond(product_summary(url.query))
        payloads = {
            '/groups': [GROUP], '/time-slots': SLOTS,
            '/weeks/current': {**WEEK, 'group_ids': [1], 'semester': {'id': 1, 'title': 'Тестовый семестр', 'total_weeks': 18}},
            '/groups/1/schedule': SCHEDULE, '/admin/stream-schedule': SCHEDULE,
            '/me': {**PROFILE, 'unread_count': int(MESSAGE['is_unread'])},
            '/me/messages': {'unread_count': int(MESSAGE['is_unread']), 'messages': [MESSAGE]},
            '/me/homework': {'can_edit': False, 'items': [HOMEWORK]}, '/me/notes': NOTES,
            '/push/config': {'public_key': None, 'fcm': False}, '/feedback/mine': FEEDBACK,
            '/lesson-types': [LESSON['type']], '/directions': [],
            '/admin/catalog': {'subjects': [LESSON['subject']], 'teachers': [LESSON['teacher']], 'rooms': [LESSON['room']]},
            '/admin/exams': EXAMS, '/admin/exams/imports': [], '/admin/imports': [],
            '/admin/messages': [],
            '/admin/feedback': [{**item, 'recipient_title': 'Деканат', 'group_id': 1, 'group_name': GROUP['name'],
                                 'author_name': PROFILE['full_name'], 'contact': None, 'contact_is_email': False,
                                 'admin_note': None} for item in FEEDBACK],
            '/admin/feedback/folders': [{'kind': 'certificate', 'title': 'Справки', 'total': len(FEEDBACK), 'new': 0}],
            '/admin/feedback/recipients': [], '/admin/groups/1/editors': [], '/admin/users': [],
            '/product/users': {'total': 1, 'items': [PRODUCT_USER]},
            '/product/users/1': {'user': PRODUCT_USER, 'counts': {'schedule_view': 7}, 'push_enabled': True},
            '/product/users/1/events': {'items': [{'id': 1, 'occurred_at': STAMP, 'name': 'schedule_view', 'platform': 'web',
                                                  'app_version': '0.1.0', 'detail': None}], 'next_before': None},
        }
        if path == '/me/messages/12':
            MESSAGE['read_at'] = '2026-11-09T10:00:00Z'
            return self.respond(MESSAGE)
        self.respond(payloads.get(path, {'detail': 'Unknown fixture endpoint'}), 200 if path in payloads else 404)

    def do_POST(self):
        global ACTIVE_DIST, WORKER_REVISION
        path = urlsplit(self.path).path.removeprefix('/api/v1')
        raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        content_type = self.headers.get('Content-Type', '')
        body = json.loads(raw) if raw and content_type.startswith('application/json') else {}
        if path == '/__fixture/activate-current' and environ.get('SMOKE_PREVIOUS_DIST'):
            ACTIVE_DIST = DIST
            return self.respond({'status': 'ok'})
        if path == '/__fixture/revise-worker' and environ.get('SMOKE_PREVIOUS_DIST'):
            WORKER_REVISION += 1
            return self.respond({'status': 'ok'})
        if path in ('/auth/admin/login', '/auth/product/login'):
            if body.get('login') != 'admin' or body.get('password') != 'fixture':
                return self.respond({'detail': 'Демо-вход: admin / fixture'}, 401)
            return self.respond(ADMIN_TOKEN)
        if path == '/auth/moodle/login':
            if body.get('username') != 'fixture' or body.get('password') != 'fixture':
                return self.respond({'detail': 'Используйте fixture / fixture'}, 401)
            return self.respond(STUDENT_TOKEN)
        if path == '/auth/student/refresh':
            return self.respond(STUDENT_TOKEN)
        if path in ('/auth/moodle/forget', '/auth/admin/logout', '/events'):
            return self.respond({'status': 'ok'})
        if path == '/me/messages/12/acknowledge':
            MESSAGE.update(acknowledged_at='2026-11-09T10:00:00Z', is_unread=False)
            return self.respond(MESSAGE)
        if path == '/me/homework/1/complete':
            HOMEWORK['completed_by_me'] = 'completed=true' in self.path
            return self.respond(HOMEWORK)
        if path == '/me/notes':
            NOTES[:] = [{'id': 1, 'occurrence_key': 'fixture-note', 'group_id': 1, 'lesson_date': body['lesson_date'], 'subject': LESSON['subject'], 'body': body['body'], 'version': 1, 'updated_at': '2026-11-09T10:00:00Z'}]
            return self.respond(NOTES[0])
        if path == '/feedback':
            return self.respond({'id': 1, 'kind_title': 'Разработчики'})
        self.respond({'detail': 'Это демонстрационный режим. Изменение данных здесь недоступно.'}, 400)

if __name__ == '__main__':
    port = int(environ.get('SMOKE_PORT', 4175))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'Mock UI only: http://127.0.0.1:{port}/ — fixture / fixture', flush=True)
    server.serve_forever()
