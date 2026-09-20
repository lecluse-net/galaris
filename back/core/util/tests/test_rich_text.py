import pytest

from core.util.rich_text import (
    RichTextError,
    convert_to_html,
    html_blocks,
    image_references,
    normalize_html,
    replace_visible_text,
    semantic_hash,
    valid_link,
    visible_text,
)

DOCUMENT = "4e98431c-c16c-4a6e-936e-15a595723340"
ATTACHMENT = "ae6942a7-b8c9-463f-8f08-8494d08ed186"


def test_code_display_options_round_trip_without_changing_semantic_content():
    plain = '<pre><code class="language-python">  print("hello")\n</code></pre>'
    source = plain.replace('<code ', '<code data-code-lines="true" data-code-nowrap="true" ')
    normalized = normalize_html(source, profile='document')
    assert 'data-code-lines="true"' in normalized
    assert 'data-code-nowrap="true"' in normalized
    assert normalize_html(normalized, profile='document') == normalized
    assert visible_text(normalized) == visible_text(plain)
    assert semantic_hash(normalized) == semantic_hash(plain)


@pytest.mark.parametrize('source', [
    '<pre><code data-code-lines="false">x</code></pre>',
    '<pre><code data-code-nowrap="anything">x</code></pre>',
    '<p data-code-lines="true">x</p>',
    '<pre data-code-nowrap="true"><code>x</code></pre>',
])
def test_code_display_options_reject_invalid_values_or_elements(source):
    with pytest.raises(RichTextError):
        normalize_html(source, profile='document')


def test_editor_corpus_round_trip():
    source = '<h2>Été</h2><p style="text-align: center"><u>été</u> <mark data-color="#fff59d" style="background-color: #fff59d">oui</mark></p><ol start="3"><li><p>A</p><ul><li><p>B</p></li></ul></li></ol><table><tbody><tr><th colspan="2" colwidth="120,180"><p>titre</p></th></tr><tr><td><p>A</p></td><td><p>B</p></td></tr></tbody></table><pre><code class="language-html">  &lt;p&gt;\n    a  b\n</code></pre>'
    normalized = normalize_html(source)
    assert normalize_html(normalized) == normalized
    assert "<u>été</u>" in normalized
    assert 'colwidth="120,180"' in normalized
    assert "  &lt;p&gt;\n    a  b\n" in normalized
    assert "A\n\tB" in visible_text(normalized)
    for block in html_blocks(normalized):
        normalize_html(block)


@pytest.mark.parametrize("kind", ["info", "warning", "question", "error", "stop", "forbidden", "search"])
def test_callout_blocks_preserve_content_and_semantic_operations(kind):
    source = f'<blockquote class="galaris-callout galaris-callout-{kind}"><h3>Title</h3><p><strong>Important</strong> text.</p><ul><li>Detail</li></ul></blockquote>'
    normalized = normalize_html(source)
    assert normalize_html(normalized) == normalized
    assert f'galaris-callout-{kind}' in normalized
    assert html_blocks(normalized) == [normalized]
    assert visible_text(normalized) == 'Title\nImportant text.\n• Detail'
    assert '<strong>Updated</strong>' in replace_visible_text(normalized, 'Important', 'Updated')
    with pytest.raises(RichTextError):
        normalize_html(source.replace(f'galaris-callout-{kind}', 'galaris-callout-unknown'))


@pytest.mark.parametrize(
    "source",
    [
        '<a href="javascript:alert(1)">a</a>',
        '<img src="https://example.com/a.png">',
        '<img src="data:image/png;base64,a">',
        '<iframe src="https://example.com"></iframe>',
        "<p><strong>x</p>",
        "<p>x",
        "<!-- hidden -->",
        "<html><body>x</body></html>",
    ],
)
def test_reject_unsupported_input(source):
    with pytest.raises(RichTextError):
        normalize_html(source, profile="document")


@pytest.mark.parametrize('source', ['<p onclick="alert(1)">a</p>', '<svg><script>x</script></svg>', '<p style="position:fixed">x</p>'])
def test_executable_html_is_reserved_for_documents(source):
    assert normalize_html(source, profile='document') == source
    with pytest.raises(RichTextError):
        normalize_html(source, profile='rich-text')


def test_archived_html_page_is_literal_text_but_cannot_be_written():
    archived = '<pre data-html-page="true"><code class="language-html">&lt;html&gt;&lt;script&gt;run()&lt;/script&gt;&lt;/html&gt;</code></pre>'
    assert visible_text(archived) == '<html><script>run()</script></html>'
    with pytest.raises(RichTextError):
        normalize_html(archived, profile="document")


def test_images_require_document_profile_and_exact_attachment_uri():
    uri = f"document://{DOCUMENT}/attachments/{ATTACHMENT}"
    source = f'<p>Illustration</p><img src="{uri}" alt="été" width="400">'
    with pytest.raises(RichTextError):
        normalize_html(source)
    assert image_references(normalize_html(source, profile="document")) == {uri}


def test_document_scripts_roundtrip_as_source_without_entering_visible_text():
    from core.util import archived_document_html
    source = '<p>Visible needle</p><script type="module">if (1 < 2) alert("a&b");</script>'
    with pytest.raises(RichTextError):
        normalize_html(source, profile="rich-text")
    assert normalize_html(source, profile="document") == source
    assert visible_text(source) == "Visible needle"
    archived = archived_document_html(source)
    assert archived == source
    assert normalize_html(archived, profile="document") == archived


def test_attachment_links_and_static_cards_roundtrip():
    uri = f"document://{DOCUMENT}/attachments/{ATTACHMENT}"
    html = f'<blockquote class="galaris-link-card"><p><a href="{uri}">Scene</a></p></blockquote>'
    assert uri in normalize_html(html, profile="document")


@pytest.mark.parametrize("kind", ["audio", "video", "pdf"])
def test_media_cards_preserve_type_without_persisting_players(kind):
    uri = f"document://{DOCUMENT}/attachments/{ATTACHMENT}"
    html = f'<blockquote class="galaris-link-card galaris-media-{kind}"><p><a href="{uri}">Recording</a></p></blockquote>'
    normalized = normalize_html(html, profile="document")
    assert f"galaris-media-{kind}" in normalized
    assert uri in normalized
    assert normalize_html(normalized, profile="document") == normalized


@pytest.mark.parametrize('source', ['/api/agents', 'https://example.com/a.js', 'https://cdn.jsdelivr.net.evil.invalid/a.js', 'https://cdn.jsdelivr.net:bad/a.js', 'javascript:alert(1)'])
def test_document_script_sources_cannot_target_application_or_arbitrary_hosts(source):
    with pytest.raises(RichTextError):
        normalize_html(f'<script src="{source}"></script>', profile='document')


@pytest.mark.parametrize("content", ["", "<p><br></p>", "<p>&nbsp; </p>"])
def test_structural_empty(content):
    assert normalize_html(content) == ""


def test_declared_format_preserves_literal_code():
    assert convert_to_html("<p>example</p>", "text/plain") == "<p>&lt;p&gt;example&lt;/p&gt;</p>"
    assert "<strong>été</strong>" in convert_to_html("**été**", "text/markdown")
    with pytest.raises(RichTextError):
        convert_to_html("![old](https://example.com/a.png)", "text/markdown")


def test_visible_edit_never_changes_attributes():
    original = '<p><a href="https://example.com/needle">needle</a></p>'
    assert (
        replace_visible_text(original, "needle", "<new>")
        == '<p><a href="https://example.com/needle">&lt;new&gt;</a></p>'
    )
    with pytest.raises(RichTextError):
        replace_visible_text("<p>x x</p>", "x", "y")
    assert semantic_hash("<p><u>Same</u></p>") == semantic_hash("<p>Same</p>")


@pytest.mark.parametrize(
    "uri",
    [
        "javascript:alert(1)",
        "goal://123",
        "//example.com",
        "https://a@b",
        "galaris://task/not-a-uuid",
    ],
)
def test_links_reject_unsupported_identity(uri):
    assert not valid_link(uri)


def test_empty_tables_and_separators_are_visible_structures():
    table = "<table><tbody><tr><td><p></p></td></tr></tbody></table>"
    assert normalize_html(table) == table
    assert normalize_html("<hr>") == "<hr>"


def test_ckeditor_figures_captions_table_properties_and_columns_round_trip():
    uri = f"document://{DOCUMENT}/attachments/{ATTACHMENT}"
    source = f'<figure class="image image_resized" style="width: 42.5%"><img src="{uri}" width="800" height="600" style="aspect-ratio: 800/600" alt="Diagram"><figcaption>Image caption</figcaption></figure><figure class="table table_resized" style="width: 75%"><table style="border: 2px solid hsl(0, 0%, 30%)"><colgroup><col style="width: 30%"><col style="width: 70%"></colgroup><tbody><tr><td style="background-color: rgb(255, 255, 255); color: black; padding: 8px; vertical-align: middle">Left</td><td>Right</td></tr></tbody></table><figcaption>Table caption</figcaption></figure>'
    saved = normalize_html(source, profile="document")
    assert normalize_html(saved, profile="document") == saved
    assert image_references(saved) == {uri}
    assert "42.5%" in saved and "30%" in saved and "70%" in saved
    assert "Image caption" in visible_text(saved)
    assert "Table caption" in visible_text(saved)
    with pytest.raises(RichTextError):
        normalize_html(source)


@pytest.mark.parametrize(
    "style",
    [
        "background-color: url(https://bad.test)",
        "color: expression(alert(1))",
        "width: 100000px",
        "font-family: url(https://bad.test)",
        "border: 1px solid var(--bad)",
    ],
)
def test_ckeditor_style_contract_rejects_active_or_unbounded_css(style):
    with pytest.raises(RichTextError):
        normalize_html(f'<p style="{style}">Safe</p>')
