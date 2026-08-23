import concurrent.futures
import datetime
import random
import time
from typing import TYPE_CHECKING, Any, Final

import yt_dlp
from youtube_transcript_api import (
    FetchedTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

import database
from models import TranscriptResult, TranscriptSnippet, VideoMetadata

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

YT_DLP_OPTS: Final[dict[str, Any]] = {
    "quiet": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
}


def _build_playlist_url(identifier: str) -> str:
    """Convert a valid ID into a playlist URL."""
    clean_id: str = identifier.strip()
    return f"https://www.youtube.com/playlist?list={clean_id}"


def _build_channel_url(identifier: str) -> str:
    """Convert a valid handle into a channel URL."""
    clean_handle: str = identifier.strip()
    if not clean_handle.startswith("@"):
        clean_handle = f"@{clean_handle}"
    return f"https://www.youtube.com/{clean_handle}/videos"


def _get_records(url: str) -> list[VideoMetadata]:
    """Scrape video metadata from either a playlist or channel URL."""
    records: list[VideoMetadata] = []

    try:
        with yt_dlp.YoutubeDL(YT_DLP_OPTS) as ydl:
            info: dict[str, Any] | None = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError:
        return records

    if info is None:
        return records

    try:
        entries: list[dict[str, Any]] = info["entries"]
    except KeyError:
        return records

    for entry in entries:
        parsed: VideoMetadata | None = _get_single_record(entry)
        if parsed is not None:
            records.append(parsed)

    return records


def _get_single_record(entry: dict[str, Any]) -> VideoMetadata | None:
    """Extract a VideoMetadata tuple from a raw yt-dlp entry dictionary."""
    try:
        video_id: str | None = entry.get("id")
    except AttributeError:
        return None

    if video_id is None:
        return None

    try:
        raw_date: str = entry["upload_date"]
        formatted_date: datetime.date | None = datetime.date(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
        )
    except KeyError, TypeError, ValueError, IndexError:
        formatted_date = None

    try:
        duration: int | None = int(entry["duration"])
    except KeyError, TypeError, ValueError:
        duration = None

    return VideoMetadata(
        video_id=video_id,
        title=entry.get("title"),
        channel=entry.get("channel") or entry.get("uploader"),
        channel_id=entry.get("channel_id") or entry.get("uploader_id"),
        upload_date=formatted_date,
        duration_seconds=duration,
    )


def _get_transcripts(
    video_ids: list[str],
    on_callback: Callable[[], None] | None = None,
    max_retries_per_video: int = 3,
    max_workers: int = 3,
) -> list[TranscriptResult]:
    """Fetch transcripts for a batch of video IDs concurrently using threads."""
    ytt_api: YouTubeTranscriptApi = YouTubeTranscriptApi()
    results: list[TranscriptResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: list[concurrent.futures.Future[TranscriptResult]] = [
            executor.submit(
                _get_single_transcript,
                video_id=video_id,
                ytt_api=ytt_api,
                max_retries=max_retries_per_video,
            )
            for video_id in video_ids
        ]

        for future in concurrent.futures.as_completed(futures):
            result: TranscriptResult | None = future.result()
            if result is not None:
                results.append(result)

            if on_callback is not None:
                on_callback()

    return results


def _get_single_transcript(
    video_id: str,
    ytt_api: YouTubeTranscriptApi,
    max_retries: int = 3,
) -> TranscriptResult:
    """Fetch one transcript with exponentially increasing delays for rate limits."""
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                time.sleep(random.uniform(0.3, 0.8))

            transcript: FetchedTranscript = ytt_api.fetch(video_id)
            return TranscriptResult(
                video_id=video_id,
                transcript=transcript,
                status="SUCCESS",
                error=None,
            )

        except (TranscriptsDisabled, NoTranscriptFound) as e:
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="NO TRANSCRIPT",
                error=str(e),
            )

        except VideoUnavailable as e:
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="UNAVAILABLE",
                error=str(e),
            )

        except Exception as e:
            if attempt == max_retries - 1:
                return TranscriptResult(
                    video_id=video_id,
                    transcript=None,
                    status="RETRYABLE",
                    error=f"ERROR: Failed after {max_retries} attempt(s): {e}",
                )

            sleep_time: float = (2**attempt) + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)

    return TranscriptResult(
        video_id=video_id,
        transcript=None,
        status="RETRYABLE",
        error="Aborted without execution",
    )


def _chunk_transcript_sliding(
    result: TranscriptResult,
    window_seconds: float = 30.0,
    overlap_seconds: float = 10.0,
) -> list[TranscriptSnippet]:
    """Group caption lines using atomic time blocks to simplify overlap math."""
    if result.transcript is None:
        return []

    raw_segments: list[dict[str, Any]] = result.transcript.to_raw_data()
    if not raw_segments:
        return []

    blocks: list[list[dict[str, Any]]] = []
    current_block: list[dict[str, Any]] = []
    block_start: float = float(raw_segments[0].get("start", 0.0))

    for seg in raw_segments:
        seg_start: float = float(seg.get("start", 0.0))

        if seg_start - block_start >= overlap_seconds:
            if current_block:
                blocks.append(current_block)
            current_block = [seg]
            block_start = seg_start
        else:
            current_block.append(seg)

    if current_block:
        blocks.append(current_block)

    # using a stride of window_length - 1, we automatically
    # get overlaps
    blocks_per_window: int = int(window_seconds // overlap_seconds)
    stride: int = blocks_per_window - 1

    if stride <= 0:
        stride = 1

    chunks: list[TranscriptSnippet] = []

    for i in range(0, len(blocks), stride):
        window_blocks: list[list[dict[str, Any]]] = blocks[i : i + blocks_per_window]

        # at the end, if only one block left,
        # adds the previous block to it to make it longer
        if len(window_blocks) == 1 and i > 0:
            window_blocks.insert(0, blocks[i - 1])

        current_text: list[str] = []
        start_time: float = float(window_blocks[0][0].get("start", 0.0))

        for block in window_blocks:
            for seg in block:
                text: str = str(seg.get("text", "")).strip()
                if text:
                    current_text.append(text)

        if current_text:
            chunks.append(
                TranscriptSnippet(
                    video_id=result.video_id,
                    start_time=start_time,
                    text=" ".join(current_text),
                ),
            )
    return chunks


def _prepare_batch_data(
    results: list[TranscriptResult],
    video_ids: list[str],
) -> tuple[dict[str, str], list[TranscriptSnippet]]:
    """Transform raw transcript results into database-ready structures."""
    status_map: dict[str, str] = {}
    chunks: list[TranscriptSnippet] = []

    for result in results:
        status_map[result.video_id] = result.status

        if result.status == "SUCCESS":
            try:
                video_chunks: list[TranscriptSnippet] = _chunk_transcript_sliding(result)
                chunks.extend(video_chunks)
            except Exception:
                status_map[result.video_id] = "RETRYABLE"

    for video_id in video_ids:
        if video_id not in status_map:
            status_map[video_id] = "RETRYABLE"

    return status_map, chunks


def process_target(
    conn: sqlite3.Connection,
    source_type: str,
    target_id: str,
    batch_size: int = 50,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    """Coordinate inserting transcript chunks from url in batches."""
    url: str = _build_playlist_url(target_id) if source_type == "Playlist" else _build_channel_url(target_id)

    records: list[VideoMetadata] = _get_records(url)
    if not records:
        return
    total_records: int = len(records)

    fetched_transcript_count = 0
    for i in range(0, total_records, batch_size):
        batch_videos: list[VideoMetadata] = records[i : i + batch_size]
        batch_video_ids: list[str] = [meta.video_id for meta in batch_videos]

        def _on_transcript_done() -> None:
            nonlocal fetched_transcript_count
            fetched_transcript_count += 1

            if progress_callback is not None:
                progress_callback(
                    fetched_transcript_count,
                    total_records,
                    f"Fetching transcripts... {fetched_transcript_count}/{total_records}",
                )

        batch_transcript_results: list[TranscriptResult] = _get_transcripts(batch_video_ids, _on_transcript_done)

        batch_status_map, batch_chunks = _prepare_batch_data(
            results=batch_transcript_results,
            video_ids=batch_video_ids,
        )

        database.batch_insert_videos(
            conn=conn,
            metadata_batch=batch_videos,
            status_map=batch_status_map,
            chunks=batch_chunks,
        )

    return
