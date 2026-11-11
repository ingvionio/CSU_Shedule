"""Local UI smoke fixture. No Moodle requests, real accounts or database writes.
Run after npm run build: python tests/smoke_server.py.
Student login: fixture / fixture; admin login: admin / fixture.
This server deliberately uses mock data and binds only to 127.0.0.1:4175.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import json

DIST = Path(__file__).resolve().parents[1] / 'dist'
GROUP = {'id': 1, 'name': 'ТЕСТ ПИ 101', 'course': 1, 'direction': 'ПИ'}
PROFILE = {'id': 1, 'full_name': 'Тестовый студент', 'group_id': 1, 'group_name': GROUP['name'], 'moodle_username': 'fixture'}
WEEK = {'number': 11, 'parity': 'odd', 'start_date': '2026-11-09', 'end_date': '2026-11-14', 'is_current': True, 'prev': 10, 'next': 12}
LESSON = {'id': 'l-1', 'note_key': 'fixture-note', 'start_time': '09:00', 'end_time': '10:30', 'slot': 1, 'subject': 'Тестовое занятие', 'type': {'code': 'lecture', 'name': 'Лекция'}, 'room': '331', 'teacher': 'Тестовый преподаватель', 'subgroup': None, 'status': 'regular', 'change': None}
MESSAGE = {'id': 12, 'title': 'Тестовое важное сообщение', 'body': 'Проверка открытия из push-ссылки и подтверждения.', 'importance': 'high', 'sent_at': '2026-11-09T09:00:00Z', 'read_at': None, 'acknowledged_at': None, 'requires_ack': True, 'is_unread': True}
HOMEWORK = {'id': 1, 'group_id': 1, 'lesson_id': 1, 'lesson_date': '2026-11-09', 'subject': LESSON['subject'], 'title': 'Тестовое задание', 'body': 'Прочитать условие.', 'due_date': '2026-11-10', 'source': 'from_class', 'status': 'published', 'version': 1, 'created_by': 1, 'created_by_name': 'Редактор группы', 'updated_by': 1, 'updated_by_name': 'Редактор группы', 'created_at': '2026-11-09T09:00:00Z', 'updated_at': '2026-11-09T09:00:00Z', 'completed_by_me': False}
NOTES = []
FEEDBACK = []

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def respond(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path.removeprefix('/api/v1')
        if not self.path.startswith('/api/'):
            return super().do_GET()
        payloads = {
            '/groups': [GROUP], '/time-slots': [{'number': 1, 'start_time': '09:00', 'end_time': '10:30'}],
            '/weeks/current': {**WEEK, 'semester': {'id': 1, 'title': 'Тестовый семестр', 'total_weeks': 18}},
            '/groups/1/schedule': {'group': GROUP, 'week': WEEK, 'generated_at': '2026-11-09T09:00:00Z', 'days': [{'date': f'2026-11-{9+i:02}', 'weekday': i+1, 'is_today': i == 0, 'lessons': [LESSON] if i == 0 else []} for i in range(6)]},
            '/me/messages': {'unread_count': int(MESSAGE['is_unread']), 'messages': [MESSAGE]},
            '/me/homework': {'can_edit': False, 'items': [HOMEWORK]}, '/me/notes': NOTES,
            '/push/config': {'public_key': None}, '/feedback/mine': FEEDBACK,
            '/lesson-types': [LESSON['type']], '/directions': [],
            '/admin/catalog': {'subjects': [LESSON['subject']], 'teachers': [LESSON['teacher']], 'rooms': [LESSON['room']]},
            '/admin/messages': [], '/admin/feedback': [], '/admin/feedback/folders': [],
            '/admin/feedback/recipients': [], '/admin/groups/1/editors': [], '/admin/users': [],
        }
        if path == '/me/messages/12':
            MESSAGE['read_at'] = '2026-11-09T10:00:00Z'
            return self.respond(MESSAGE)
        self.respond(payloads.get(path, {'detail': 'Unknown fixture endpoint'}), 200 if path in payloads else 404)

    def do_POST(self):
        path = urlsplit(self.path).path.removeprefix('/api/v1')
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or '{}')
        if path == '/auth/admin/login':
            if body.get('login') != 'admin' or body.get('password') != 'fixture':
                return self.respond({'detail': 'Демо-вход: admin / fixture'}, 401)
            return self.respond({'access_token': 'test-only-admin-token', 'token_type': 'bearer', 'expires_at': '2099-01-01T00:00:00Z'})
        if path == '/auth/moodle/login':
            if body.get('username') != 'fixture' or body.get('password') != 'fixture':
                return self.respond({'detail': 'Используйте fixture / fixture'}, 401)
            return self.respond({'access_token': 'test-only-token', 'token_type': 'bearer', 'expires_at': '2099-01-01T00:00:00Z', 'profile': PROFILE})
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
    print('Mock UI only: http://127.0.0.1:4175/ — fixture / fixture', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 4175), Handler).serve_forever()
