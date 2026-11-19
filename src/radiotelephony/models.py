from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuestionReference(BaseModel):
    model_config = ConfigDict(extra="allow")

    chapter: int | None = None
    chapter_title: str | None = None
    section: str | None = None
    section_title: str | None = None
    paragraph: str | None = None
    page_printed: str | int | None = None
    page_pdf: int | None = Field(default=None, ge=1)


class Question(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    question_type: str = "knowledge_check"
    category: str = "general"
    level: int = Field(default=1, ge=1, le=3)
    tags: list[str] = Field(default_factory=list)

    question: str = Field(min_length=1, max_length=300)
    options: list[str]
    answer_index: int = Field(ge=0, le=3)

    short_explanation: str = Field(default="", max_length=200)
    explanation: str = ""

    reference: QuestionReference | None = None
    anchor: str | None = None

    is_active: bool = True

    @field_validator("options")
    @classmethod
    def validate_options(cls, value):
        if len(value) != 4:
            raise ValueError("Exactly four options are required")

        for option in value:
            if not option.strip():
                raise ValueError("Options cannot be empty")
            if len(option) > 100:
                raise ValueError("Telegram options cannot exceed 100 characters")

        return value
