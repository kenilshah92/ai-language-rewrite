from types import SimpleNamespace

from app.humanizer import Humanizer
from app.models import TextBlock

import pymupdf as fitz


class FakeResponses:
    def create(self, **kwargs):
        assert "maximum_characters" in kwargs["input"]
        return SimpleNamespace(output_text='{"rewrites":[{"id":"p1-b1","text":"Clearer copy"}]}')


class FakeClient:
    responses = FakeResponses()


def test_humanizer_maps_rewrites_by_id(tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Rewrite naturally.", encoding="utf-8")
    block = TextBlock("p1-b1", 0, fitz.Rect(0, 0, 100, 30), "Original copy", "Helvetica", 12, (0, 0, 0))
    result = Humanizer(prompt, "test-model", client=FakeClient()).rewrite([block])
    assert result == {"p1-b1": "Clearer copy"}


def test_duplicate_ids_are_rejected(tmp_path):
    import pytest
    from app.humanizer import HumanizerError
    prompt = tmp_path / 'prompt.md'
    prompt.write_text('Rewrite naturally.')
    block = TextBlock('p1-b1', 0, fitz.Rect(0, 0, 100, 30), 'Original copy', 'Helvetica', 12, (0, 0, 0))
    fake = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: SimpleNamespace(output_text='{"rewrites":[{"id":"p1-b1","text":"One"},{"id":"p1-b1","text":"Two"}]}')))
    with pytest.raises(HumanizerError):
        Humanizer(prompt, 'test', client=fake).rewrite([block])
