from core.database import get_db

ADMIN_ROLE_CODE: str = "admin"
ADMIN_ROLE_DISPLAY_NAME: str = "role.admin"


async def update_admin_role() -> None:
    """Compatibility facade applying the authoritative DbAdmin datasets."""

    from core.dbadmin import reconcile_dataset

    from .dbadmin import datasets

    db = get_db()
    by_key = {dataset.key: dataset for dataset in datasets()}
    for key in ("core.authorize.admin_role", "core.authorize.admin_grants"):
        await reconcile_dataset(db, by_key[key])
