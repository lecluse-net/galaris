import pytest

from core.storage import FileRename, validate_file_name


@pytest.mark.parametrize("name", ["", "   ", ".", "..", "../report.txt", "folder/report.txt", "folder\\report.txt", "a\nb.txt", "a\x00b.txt", "x" * 501])
def test_rename_rejects_invalid_file_names(name):
    with pytest.raises(ValueError):
        validate_file_name(name)
    with pytest.raises(ValueError):
        FileRename(name=name)


def test_rename_preserves_complete_unicode_name_and_extension():
    assert FileRename(name="  Re\u0301sultat final.tar.gz  ").name == "Résultat final.tar.gz"
