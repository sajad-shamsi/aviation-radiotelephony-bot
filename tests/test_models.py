import pytest
from pydantic import ValidationError

from radiotelephony.models import Question


def sample_question():
    return {
        "id": "TEST-001",
        "question_type": "scenario",
        "category": "general",
        "level": 2,
        "tags": ["test"],
        "question": "What should the pilot do?",
        "options": ["A", "B", "C", "D"],
        "answer_index": 1,
        "short_explanation": "توضیح آزمایشی",
        "explanation": "توضیح کامل آزمایشی",
        "reference": {
            "chapter": 1,
            "section": "1.1",
            "page_pdf": 10,
        },
        "anchor": "test anchor",
    }


def test_valid_question():
    question = Question.model_validate(sample_question())
    assert question.id == "TEST-001"
    assert question.answer_index == 1


def test_question_requires_four_options():
    data = sample_question()
    data["options"] = ["A", "B", "C"]

    with pytest.raises(ValidationError):
        Question.model_validate(data)


def test_persian_explanations_are_preserved():
    question = Question.model_validate(sample_question())
    assert question.short_explanation == "توضیح آزمایشی"
