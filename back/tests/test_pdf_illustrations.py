"""Synthetic PDF imports keep figures without embedding editable paragraphs twice."""

from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from core.document.worker import prepare


def source_pdf(path, *, graphic="raster", rotation=0, scanned=False, with_text=True, label=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    resources = DictionaryObject()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    paragraph = b"BT /F1 18 Tf 30 740 Td (Synthetic editable paragraph above the illustration.) Tj ET\n" if with_text else b""
    if graphic in {"raster", "nested"}:
        image = Image.new("RGB", (120, 90), "red")
        obj = DecodedStreamObject()
        obj.set_data(image.tobytes())
        obj.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image.width), NameObject("/Height"): NumberObject(image.height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"), NameObject("/BitsPerComponent"): NumberObject(8)})
        resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Im1"): writer._add_object(obj)})
        picture = b"q 160 0 0 120 40 400 cm /Im1 Do Q"
        if graphic == "nested":
            form = DecodedStreamObject()
            form.set_data(b"q 160 0 0 120 0 0 cm /Im1 Do Q")
            from pypdf.generic import ArrayObject
            form.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 160, 120)]),
                NameObject("/Resources"): resources})
            resources = DictionaryObject({NameObject("/Font"): resources["/Font"],
                NameObject("/XObject"): DictionaryObject({NameObject("/Fm1"): writer._add_object(form)})})
            picture = b"q 1 0 0 1 40 400 cm /Fm1 Do Q"
    elif graphic == "vector":
        picture = b"1 1 1 rg 0 0 600 800 re f\n1 0 0 rg 40 400 160 120 re f"
    else:
        picture = b""
    if label:
        picture += b"\n0 0 0 rg BT /F1 12 Tf 60 440 Td (Synthetic diagram label) Tj ET"
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(picture + b"\n" + paragraph)
    page[NameObject("/Contents")] = writer._add_object(stream)
    if rotation:
        page.rotate(rotation)
    if scanned:
        import pypdfium2 as pdfium
        buffer = BytesIO()
        writer.write(buffer)
        with pdfium.PdfDocument(buffer.getvalue()) as pdf:
            bitmap = pdf[0].render(scale=2)
            image = bitmap.to_pil().copy()
            bitmap.close()
        image.save(path, format="PDF", resolution=144)
    else:
        writer.write(path)


@pytest.mark.parametrize("graphic,rotation", [("raster", 0), ("vector", 0), ("nested", 0), ("raster", 90)])
def test_editable_pdf_keeps_only_the_illustration_and_preserves_evidence(tmp_path, graphic, rotation):
    path = tmp_path / "source.pdf"
    source_pdf(path, graphic=graphic, rotation=rotation)
    directory = tmp_path / "editable"
    result = prepare(path, path.name, "application/pdf", directory, editable=True)
    assert result["html"].count("Synthetic editable paragraph") == 1
    assert len(result["assets"]) == 1
    with Image.open(directory / result["assets"][0]) as image:
        pixels = list(image.convert("RGB").get_flattened_data())
        assert any(r > 180 and g < 80 and b < 80 for r, g, b in pixels)
        assert not any(max(pixel) < 80 for pixel in pixels), "The paragraph was embedded a second time"
    evidence = prepare(path, path.name, "application/pdf", tmp_path / "evidence")
    assert evidence["pages"][0]["image"]
    assert "Synthetic editable paragraph" in evidence["pages"][0]["text"]
    assert prepare(path, path.name, "application/pdf", directory, editable=True) == result
    (directory / result["assets"][0]).unlink()
    assert prepare(path, path.name, "application/pdf", directory, editable=True) == result
    assert (directory / result["assets"][0]).is_file()


@pytest.mark.parametrize("graphic", ["none", "raster"])
def test_scanned_pdf_separates_recognized_text_from_pictures(tmp_path, graphic):
    path = tmp_path / "scan.pdf"
    source_pdf(path, graphic=graphic, scanned=True)
    directory = tmp_path / "editable"
    result = prepare(path, path.name, "application/pdf", directory, editable=True)
    assert "Synthetic editable paragraph" in result["html"]
    assert result["pages"][0]["ocr"]
    assert len(result["assets"]) == (0 if graphic == "none" else 1)
    for asset in result["assets"]:
        with Image.open(directory / asset) as image:
            pixels = list(image.convert("RGB").get_flattened_data())
            assert any(r > 180 and g < 80 and b < 80 for r, g, b in pixels)
            assert not any(max(pixel) < 80 for pixel in pixels)


def test_text_only_pdf_does_not_create_a_page_image_in_the_document(tmp_path):
    path = tmp_path / "text.pdf"
    source_pdf(path, graphic="none")
    result = prepare(path, path.name, "application/pdf", tmp_path / "editable", editable=True)
    assert "Synthetic editable paragraph" in result["html"]
    assert "<img" not in result["html"] and result["assets"] == []


def test_diagram_labels_are_kept_inside_the_figure_without_duplicate_editable_text(tmp_path):
    path = tmp_path / "diagram.pdf"
    source_pdf(path, graphic="vector", label=True)
    directory = tmp_path / "editable"
    result = prepare(path, path.name, "application/pdf", directory, editable=True)
    assert "Synthetic editable paragraph" in result["html"]
    assert "Synthetic diagram label" not in result["html"]
    with Image.open(directory / result["assets"][0]) as image:
        assert any(max(pixel) < 80 for pixel in image.convert("RGB").get_flattened_data())


def test_interrupted_editable_conversion_resumes_with_all_illustrations(tmp_path, monkeypatch):
    from pypdf import PdfReader
    from core.document import pdf_illustrations

    path = tmp_path / "source.pdf"
    source_pdf(path)
    reader = PdfReader(path)
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    writer.add_page(reader.pages[0])
    writer.write(path)
    original = pdf_illustrations.page_content
    visited = []

    def interrupted(page, bitmap, text, directory, number):
        visited.append(number)
        if number == 2:
            raise RuntimeError("Synthetic illustration interruption")
        return original(page, bitmap, text, directory, number)

    directory = tmp_path / "editable"
    with monkeypatch.context() as patch:
        patch.setattr(pdf_illustrations, "page_content", interrupted)
        with pytest.raises(RuntimeError, match="Synthetic illustration interruption"):
            prepare(path, path.name, "application/pdf", directory, editable=True)
    assert visited == [1, 2]
    result = prepare(path, path.name, "application/pdf", directory, editable=True)
    assert len(result["pages"]) == 2 and len(result["assets"]) == 2
    assert result["html"].count("Synthetic editable paragraph") == 2
    assert all((directory / asset).is_file() for asset in result["assets"])
