from typing import Literal

from pydantic import BaseModel, Field


class Counts(BaseModel):
    new: int
    learning: int
    review: int


class DeckNode(BaseModel):
    id: int
    name: str
    full_name: str
    level: int
    collapsed: bool
    counts: Counts
    children: list["DeckNode"] = []


class AvItem(BaseModel):
    type: Literal["sound", "tts"]
    url: str | None = None
    text: str | None = None
    lang: str | None = None
    speed: float | None = None


class StudyCard(BaseModel):
    card_id: int
    note_id: int
    deck_id: int
    queue: Literal["new", "learning", "review"]
    question_html: str
    answer_html: str
    css: str
    card_class: str
    question_av: list[AvItem]
    answer_av: list[AvItem]
    autoplay: bool
    # etichette dei 4 pulsanti: [Di nuovo, Difficile, Bene, Facile] es. ["<1m", "6m", "10m", "4g"]
    button_labels: list[str]
    flag: int
    tags: list[str]


class StudyState(BaseModel):
    done: bool
    counts: Counts
    card: StudyCard | None = None


class AnswerIn(BaseModel):
    card_id: int
    rating: Literal[1, 2, 3, 4] = Field(description="1=Di nuovo 2=Difficile 3=Bene 4=Facile")
    time_taken_ms: int = Field(ge=0, le=60 * 60 * 1000)


class FlagIn(BaseModel):
    flag: int = Field(ge=0, le=7)


class NotetypeField(BaseModel):
    name: str
    ord: int


class Notetype(BaseModel):
    id: int
    name: str
    is_cloze: bool
    fields: list[NotetypeField]


class NoteIn(BaseModel):
    deck_id: int
    notetype_id: int
    fields: dict[str, str]
    tags: list[str] = []


class NoteUpdate(BaseModel):
    fields: dict[str, str] | None = None
    tags: list[str] | None = None


class NoteOut(BaseModel):
    id: int
    notetype_id: int
    fields: dict[str, str]
    tags: list[str]
    card_ids: list[int]


class LoginIn(BaseModel):
    username: str
    password: str


class FullSyncIn(BaseModel):
    direction: Literal["upload", "download"]


class SyncResultOut(BaseModel):
    outcome: str
    finished_at: float
    server_message: str = ""
    error: str | None = None


class SyncStatusOut(BaseModel):
    logged_in: bool
    username: str | None
    last_result: SyncResultOut | None
    media: dict


class TodayStats(BaseModel):
    reviews: int
    seconds: int
    again: int
    summary: str
