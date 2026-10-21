import io
import zipfile

import pytest

import style
import wordfiles


def test_zip_bombs_are_refused_before_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", b"\0" * (60 * 1024 * 1024))  # 60 MB unpacked, ~60 KB packed
    data = buf.getvalue()
    assert len(data) < wordfiles.MAX_UPLOAD
    with pytest.raises(wordfiles.BadFile, match="too large"):
        wordfiles.read_docx(data)


def test_oversized_uploads_are_refused():
    with pytest.raises(wordfiles.BadFile, match="5 MB"):
        wordfiles.read_docx(b"x" * (wordfiles.MAX_UPLOAD + 1))


def test_title_heading_is_not_copied_into_the_body():
    data = wordfiles.write_docx("My Title", "One.\n\nTwo.")
    assert wordfiles.read_docx(data) == ("My Title", "One.\n\nTwo.")


def test_generic_phrases_are_found_case_insensitively_and_keep_original_text():
    flags = style.generic_phrase_flags("It Is Important To Note that we delve into it.")
    found = {f["original"] for f in flags}
    assert "It Is Important To Note" in found and "delve into" in found
    assert all(f["revised"] is None for f in flags)


def test_voice_profile_measures_contractions_and_rhythm():
    stats = style.profile_stats(["I didn't think so. Honestly? No. It's a long story that I won't tell today."])
    assert stats["contractions_per_100_words"] > 1.5
    assert "Uses contractions freely" in style.describe_voice(stats)


def test_voice_comparison_notices_a_stiffer_draft():
    usual = style.profile_stats(["I didn't. You can't. It's fine. We're here. They'll go. I'm done."])
    notes = style.compare("I did not. You cannot. It is fine. We are here. They will go. I am done.", usual)
    assert any("contractions" in n for n in notes)
