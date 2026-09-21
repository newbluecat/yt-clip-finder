from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from datetime import date

    from youtube_transcript_api import FetchedTranscript


class VideoMetadata(NamedTuple):
    """Contains all relevant video metadata."""

    video_id: str
    title: str | None
    channel: str | None
    channel_id: str | None
    upload_date: date | None
    duration_seconds: int | None


class TranscriptResult(NamedTuple):
    """Contains the output of youtube_transcript_api.fetch()."""

    video_id: str
    transcript: FetchedTranscript | None
    status: str


class TranscriptSnippet(NamedTuple):
    """Contains a restructured snippet of the TranscriptResult."""

    video_id: str
    start_time: float
    text: str


class SearchParams(NamedTuple):
    """Encapsulates all parameters for a search operation."""

    source_type: str
    target_id: str
    query: str
    start_date: date | None
    end_date: date | None
    limit: int = 100


class SearchResult(NamedTuple):
    """Results of a search of the sqlite3 database."""

    video_id: str
    title: str
    channel: str
    start_time: float
    snippet: str
    rank: float
