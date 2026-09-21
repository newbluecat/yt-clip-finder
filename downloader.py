from __future__ import annotations

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
from models import SearchParams, TranscriptResult, TranscriptSnippet, VideoMetadata

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Callable

YT_DLP_OPTS: Final[dict[str, Any]] = {
    "quiet": True,
    "extract_flat": "in_playlist",
    "skip_download": True,
    "playlistend": 10000,
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
    """Scrape video metadata from URL with a single yt-dlp request."""
    records: list[VideoMetadata] = []

    # if playlist doesn't exist, let process_target handle it
    with yt_dlp.YoutubeDL(YT_DLP_OPTS) as ydl:
        info: dict[str, Any] | None = ydl.extract_info(url, download=False)

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
    """Extract a VideoMetadata tuple from dict of yt-dlp entries."""
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
    is_cancelled: Callable[[], bool] | None = None,
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
            if is_cancelled is not None and is_cancelled():
                for f in futures:
                    f.cancel()
                break

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
            )

        except VideoUnavailable, TranscriptsDisabled:
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="UNAVAILABLE",
            )

        except NoTranscriptFound:
            return TranscriptResult(
                video_id=video_id,
                transcript=None,
                status="RETRYABLE",
            )

        except Exception:
            if attempt == max_retries - 1:
                return TranscriptResult(
                    video_id=video_id,
                    transcript=None,
                    status="RETRYABLE",
                )

            sleep_time: float = (2**attempt) + random.uniform(0.5, 1.5)
            time.sleep(sleep_time)

    return TranscriptResult(
        video_id=video_id,
        transcript=None,
        status="RETRYABLE",
    )


def _build_atomic_blocks(
    raw_segments: list[dict[str, Any]],
    overlap_seconds: float,
) -> list[list[dict[str, Any]]]:
    """Group raw segments into discrete atomic time blocks."""
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

    return blocks


def _build_sliding_chunks(
    blocks: list[list[dict[str, Any]]],
    video_id: str,
    window_seconds: float,
    overlap_seconds: float,
) -> list[TranscriptSnippet]:
    """Slide a window over atomic blocks to create overlapping text chunks."""
    blocks_per_window: int = int(window_seconds // overlap_seconds)
    stride: int = max(1, blocks_per_window - 1)
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
                    video_id=video_id,
                    start_time=start_time,
                    text=" ".join(current_text),
                ),
            )

    return chunks


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

    blocks: list[list[dict[str, Any]]] = _build_atomic_blocks(raw_segments, overlap_seconds)

    return _build_sliding_chunks(
        blocks=blocks,
        video_id=result.video_id,
        window_seconds=window_seconds,
        overlap_seconds=overlap_seconds,
    )


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


def _filter_metadata(
    conn: sqlite3.Connection,
    metadata: list[VideoMetadata],
    start_date: datetime.date | None,
    end_date: datetime.date | None,
) -> tuple[list[VideoMetadata], int, int]:
    """Filter metadata by date and database existence, returning missing videos and counts."""
    filtered_metadata: list[VideoMetadata] = []
    for meta in metadata:
        if start_date is not None and meta.upload_date is not None and meta.upload_date < start_date:
            continue
        if end_date is not None and meta.upload_date is not None and meta.upload_date > end_date:
            continue
        filtered_metadata.append(meta)

    if not filtered_metadata:
        return [], 0, len(filtered_metadata)

    filtered_ids: list[str] = [meta.video_id for meta in filtered_metadata]
    existing_ids: set[str] = database.get_existing_video_ids(conn, filtered_ids)

    missing_metadata: list[VideoMetadata] = [vid for vid in filtered_metadata if vid.video_id not in existing_ids]

    total_count: int = len(filtered_metadata)
    skipped_count: int = total_count - len(missing_metadata)

    return missing_metadata, total_count, skipped_count


def _process_batches(
    conn: sqlite3.Connection,
    missing_metadata: list[VideoMetadata],
    batch_size: int,
    skipped_count: int,
    progress_callback: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Iterate through missing metadata to fetch and save transcripts in batches."""
    missing_count: int = len(missing_metadata)
    fetched_transcript_count: int = 0

    for i in range(0, missing_count, batch_size):
        if is_cancelled is not None and is_cancelled():
            if progress_callback is not None:
                progress_callback(fetched_transcript_count, missing_count, "Search aborted")
            return

        batch_videos: list[VideoMetadata] = missing_metadata[i : i + batch_size]
        missing_ids: list[str] = [vid.video_id for vid in batch_videos]

        def _on_transcript_done() -> None:
            nonlocal fetched_transcript_count
            fetched_transcript_count += 1

            if is_cancelled is not None and is_cancelled():
                return

            if progress_callback is not None:
                progress_callback(
                    fetched_transcript_count,
                    missing_count,
                    f"Fetching transcripts... {fetched_transcript_count}/{missing_count} (Skipped: {skipped_count})",
                )

        batch_transcript_results: list[TranscriptResult] = _get_transcripts(
            video_ids=missing_ids,
            on_callback=_on_transcript_done,
            is_cancelled=is_cancelled,
        )

        batch_status_map: dict[str, str]
        batch_chunks: list[TranscriptSnippet]
        batch_status_map, batch_chunks = _prepare_batch_data(
            results=batch_transcript_results,
            video_ids=missing_ids,
        )

        database.batch_insert_videos(
            conn=conn,
            metadata_batch=batch_videos,
            status_map=batch_status_map,
            chunks=batch_chunks,
        )

        if is_cancelled is not None and is_cancelled():
            if progress_callback is not None:
                progress_callback(fetched_transcript_count, missing_count, "Search aborted")
            return


def process_target(
    conn: sqlite3.Connection,
    search_params: SearchParams,
    batch_size: int = 50,
    progress_callback: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Coordinate inserting transcript chunks from url in batches."""
    url: str = (
        _build_playlist_url(search_params.target_id)
        if search_params.source_type == "Playlist"
        else _build_channel_url(search_params.target_id)
    )

    metadata: list[VideoMetadata] = _get_records(url)
    if not metadata:
        if progress_callback is not None:
            progress_callback(0, 0, f"{search_params.source_type} has no videos")
        return

    missing_metadata, total_count, skipped_count = _filter_metadata(
        conn,
        metadata,
        search_params.start_date,
        search_params.end_date,
    )

    if total_count == 0:
        if progress_callback is not None:
            progress_callback(100, 100, f"{search_params.source_type} has no videos within the specified dates")
        return

    if not missing_metadata:
        if progress_callback is not None:
            progress_callback(100, 100, "All videos are already processed")
        return

    _process_batches(
        conn=conn,
        missing_metadata=missing_metadata,
        batch_size=batch_size,
        skipped_count=skipped_count,
        progress_callback=progress_callback,
        is_cancelled=is_cancelled,
    )
