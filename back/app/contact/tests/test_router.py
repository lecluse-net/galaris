from app.contact import router


def test_contact_endpoints_reuse_memory_privileges() -> None:
    assert router.read_contacts._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        "MEMORY_ACCESS",
        "MEMORY_EDIT",
        "MEMORY_ADMIN",
    ]
    assert router.merge_contacts._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        "MEMORY_EDIT"
    ]
    assert router.forget_contact._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        "MEMORY_EDIT"
    ]
