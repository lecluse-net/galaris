from core.authorize.privilege_service import PrivilegeService
from core.authorize.update_admin_role import ADMIN_ROLE_DISPLAY_NAME


def test_bundled_authorization_labels_are_frontend_translation_keys() -> None:
    privileges = PrivilegeService().get_code_privileges()

    assert privileges
    assert ADMIN_ROLE_DISPLAY_NAME == "role.admin"
    assert {
        code: label
        for code, label in privileges.items()
        if label != f"privilege.{code}"
    } == {}
