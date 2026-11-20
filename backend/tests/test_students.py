"""Профиль студента после подтверждённого входа Moodle, роли токенов."""

from tests.moodle_helpers import login_student

DEVICE = "device-key-0123456789"
OTHER_DEVICE = "device-key-9876543210"


def register(client, group_id, name="Иванов Иван", device=DEVICE):
    return login_student(client, group_id, name, device)


def student_headers(client, group_id, **kwargs) -> dict[str, str]:
    response = register(client, group_id, **kwargs)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_вход_и_профиль(bare_client, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    response = register(bare_client, group_id, name="  Иванов   Иван ")
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["full_name"] == "Иванов Иван"
    assert profile["group_name"] == "ТЕСТ ПИ 991"

    headers = {"Authorization": f"Bearer {response.json()['access_token']}"}
    me = bare_client.get("/api/v1/me", headers=headers).json()
    assert me["id"] == profile["id"]
    assert me["unread_count"] == 0


def test_повторный_вход_той_же_учётной_записи_обновляет_профиль(bare_client, test_groups):
    first = register(bare_client, test_groups["ТЕСТ ПИ 991"]).json()["profile"]
    again = register(bare_client, test_groups["ТЕСТ ПИ 992"], name="Иванов Иван Петрович").json()["profile"]
    assert again["id"] == first["id"]
    assert again["group_name"] == "ТЕСТ ПИ 992"
    assert again["full_name"] == "Иванов Иван Петрович"


def test_разные_учётные_записи_с_одинаковым_фио_не_объединяются(bare_client, test_groups):
    group_id = test_groups["ТЕСТ ПИ 991"]
    first = register(bare_client, group_id).json()["profile"]
    other = register(bare_client, group_id, device=OTHER_DEVICE).json()["profile"]
    assert other["id"] != first["id"]


def test_неизвестная_группа(bare_client, test_groups):
    assert register(bare_client, 999_999).status_code == 404


def test_студенческий_токен_не_пускает_в_админку(bare_client, test_groups):
    headers = student_headers(bare_client, test_groups["ТЕСТ ПИ 991"])
    assert bare_client.get("/api/v1/admin/catalog", headers=headers).status_code == 403
    assert bare_client.get("/api/v1/admin/feedback/folders", headers=headers).status_code == 403


def test_админский_токен_не_пускает_в_me(bare_client, bare_admin_headers, test_groups):
    assert bare_client.get("/api/v1/me", headers=bare_admin_headers).status_code == 403
    assert bare_client.get("/api/v1/me").status_code == 401
