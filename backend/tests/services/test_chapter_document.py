from app.services.chapter_document import from_html, from_text


def test_markup_is_sanitized_and_block_ids_survive_unrelated_insertions():
    value = '<h2>Heading</h2><p>Hello <em>reader</em>.</p><script>alert(1)</script><p onclick="bad()"><a href="javascript:bad()">Link</a></p>'
    document = from_html(value)
    rendered = "".join(block["html"] for block in document["blocks"])
    assert "<em>reader</em>" in rendered
    assert "script" not in rendered and "onclick" not in rendered and "javascript:" not in rendered
    changed = from_html("<p>Preface</p>" + value)
    assert changed["blocks"][2]["id"] == document["blocks"][1]["id"]
    assert document["plain_text"].startswith("Heading\n\nHello reader.")


def test_text_is_never_interpreted_as_markup():
    document = from_text("<script>original text</script>")
    assert document["blocks"][0]["html"] == "<p>&lt;script&gt;original text&lt;/script&gt;</p>"


def test_plain_text_keeps_list_and_table_cells_separate_for_speech():
    document = from_html("<ul><li>First</li><li>Second</li></ul><table><tr><td>Name</td><td>Place</td></tr></table>")
    assert document["blocks"][0]["text"] == "First\nSecond"
    assert document["blocks"][1]["text"] == "Name\nPlace"


def test_layout_wrappers_do_not_collapse_paragraphs_or_change_their_anchors():
    wrapped = from_html("<div><div><p>One.</p><p>Two <em>words</em>.</p></div></div>")
    unwrapped = from_html("<p>One.</p><p>Two <em>words</em>.</p>")
    assert wrapped == unwrapped


def test_div_based_paragraphs_remain_distinct():
    document = from_html("<div>One.</div><div><strong>Two.</strong></div>")
    assert [block["text"] for block in document["blocks"]] == ["One.", "Two."]
    assert document["blocks"][1]["html"] == "<p><strong>Two.</strong></p>"


def test_source_author_note_wrappers_preserve_formatting_and_end_at_their_boundary():
    note = '<div class="notes module"><h3>Author’s note</h3><blockquote><p>Thanks <em>reader</em>.</p></blockquote><script>unsafe()</script></div>'
    document = from_html(note + "<p>The story.</p>")
    assert [block.get("role") for block in document["blocks"]] == ["author_note", "author_note", None]
    assert all(block["role_provenance"] == "source" for block in document["blocks"][:2])
    assert "<em>reader</em>" in document["blocks"][1]["html"]
    assert "unsafe" not in document["plain_text"]
    assert document["blocks"][-1]["text"] == "The story."


def test_note_roles_change_versions_without_changing_their_text_anchors():
    ordinary = from_html("<p>Same paragraph.</p>")
    note = from_html('<aside class="author-note"><p>Same paragraph.</p></aside>')
    assert note["blocks"][0]["id"] == ordinary["blocks"][0]["id"]
    assert note["content_version"] != ordinary["content_version"]
    assert from_html('<section data-nexus-role="author_note"><p>Same paragraph.</p></section>') == note


def test_unclosed_paragraph_does_not_leak_note_role_into_following_story():
    document = from_html('<div class="author-notes"><p>Note text.</div><p>Story text.</p>')
    assert [block["text"] for block in document["blocks"]] == ["Note text.", "Story text."]
    assert document["blocks"][0]["role"] == "author_note"
    assert "role" not in document["blocks"][1]


def test_ordinary_notes_classes_and_note_labels_inside_muted_markup_do_not_classify_prose():
    document = from_html('<div class="notes"><p>Story text.</p></div><script><div class="author-note">Unsafe</div></script><p>Next.</p>')
    assert [block["text"] for block in document["blocks"]] == ["Story text.", "Next."]
    assert all("role" not in block for block in document["blocks"])


def test_excessive_source_nesting_is_rejected():
    import pytest
    with pytest.raises(ValueError, match="nesting limit"):
        from_html("<div>" * 300 + "Deep content" + "</div>" * 300)


def test_plain_text_note_identity_is_shared_with_derivatives_and_stops_at_story_boundaries():
    document = from_text("Author’s note: start.\nStory.\nNote: an in-story message.\nMore story.\nAN: end.")
    assert [block.get("role") for block in document["blocks"]] == ["author_note", None, None, None, "author_note"]
    assert document["blocks"][0]["role_provenance"] == "heuristic"


def test_story_evidence_excludes_author_commentary_before_inference():
    from app.services.chapter_document import story_blocks
    document = from_html('<aside class="author-note"><p>Future commentary.</p></aside><p>Seen story.</p><aside class="author-note"><p>Another aside.</p></aside>')
    assert [block["text"] for block in story_blocks(document)] == ["Seen story."]
    older = from_html("<p>A/N: A hidden future aside.</p><p>Seen story.</p>")
    assert [block["text"] for block in story_blocks(older)] == ["Seen story."]
