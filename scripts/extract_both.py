#!/usr/bin/env python3
"""Detect scenes on reference + raw footage; write CSVs and midpoint thumbnails."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import cv2
from scenedetect import ContentDetector, detect


def project_root() -> Path:
    """Project root = parent of scripts/."""
    return Path(__file__).resolve().parent.parent


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm (milliseconds, 3 digits)."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000.0))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def video_duration_seconds(video_path: Path) -> float | None:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    cap.release()
    if fps <= 0 or frame_count <= 0:
        return None
    return float(frame_count / fps)


def extract_midpoint_frame(
    video_path: Path,
    midpoint_sec: float,
    out_path: Path,
) -> bool:
    """Seek to midpoint and write a high-quality JPEG. Returns True on success."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"ERROR: Could not open video for frame extract: {video_path}", file=sys.stderr)
        return False

    cap.set(cv2.CAP_PROP_POS_MSEC, midpoint_sec * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if fps > 0:
            frame_idx = int(midpoint_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        print(
            f"WARNING: Failed to read frame at {format_timestamp(midpoint_sec)}; "
            f"skipping thumbnail {out_path.name}",
            file=sys.stderr,
        )
        return False

    ok = cv2.imwrite(str(out_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        print(f"ERROR: Failed to write thumbnail: {out_path}", file=sys.stderr)
        return False
    return True


def analyze_video(
    video_path: Path,
    csv_path: Path,
    thumbs_dir: Path,
    label: str,
) -> int:
    """
    Run ContentDetector on video_path.
    Write scenes CSV + midpoint JPEGs.
    Returns number of scenes written, or -1 on hard failure.
    """
    print(f"[extract_both] === {label} ===")
    print(f"[extract_both] Video: {video_path}")
    print(f"[extract_both] CSV:   {csv_path}")
    print(f"[extract_both] Thumbs:{thumbs_dir}")

    if not video_path.is_file():
        print(f"ERROR: Missing video for {label}: {video_path}", file=sys.stderr)
        return -1

    thumbs_dir.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # Clear prior thumbnails for this target (keep .gitkeep)
    for old in thumbs_dir.glob("scene_*.jpg"):
        try:
            old.unlink()
        except OSError as exc:
            print(f"WARNING: Could not remove old thumbnail {old}: {exc}", file=sys.stderr)

    print(f"[extract_both] Detecting scenes ({label}) with ContentDetector…")
    try:
        scene_list = detect(str(video_path), ContentDetector())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Scene detection failed for {label}: {exc}", file=sys.stderr)
        return -1

    use_float_pairs = False
    if not scene_list:
        print(
            f"WARNING: No scene cuts detected in {label}. "
            "Falling back to a single full-clip scene."
        )
        duration = video_duration_seconds(video_path)
        if duration is None:
            print(f"ERROR: Unable to determine duration for {label}.", file=sys.stderr)
            return -1
        scene_list = [(0.0, duration)]
        use_float_pairs = True

    print(f"[extract_both] {label}: {len(scene_list)} scene(s). Writing CSV + thumbnails…")

    rows: list[dict[str, str]] = []
    for index, scene in enumerate(scene_list, start=1):
        if use_float_pairs:
            start_sec = float(scene[0])
            end_sec = float(scene[1])
        else:
            start_tc, end_tc = scene
            start_sec = start_tc.get_seconds()
            end_sec = end_tc.get_seconds()

        duration_sec = max(0.0, end_sec - start_sec)
        midpoint = (start_sec + end_sec) / 2.0
        start_str = format_timestamp(start_sec)
        end_str = format_timestamp(end_sec)
        thumb_name = f"scene_{index:03d}.jpg"
        thumb_path = thumbs_dir / thumb_name

        print(
            f"  [{label}] Scene {index:03d}: {start_str} → {end_str} "
            f"({duration_sec:.3f}s, mid {format_timestamp(midpoint)}) → {thumb_name}"
        )
        extract_midpoint_frame(video_path, midpoint, thumb_path)

        rows.append(
            {
                "Scene_Number": str(index),
                "Start_Time (HH:MM:SS.ms)": start_str,
                "End_Time (HH:MM:SS.ms)": end_str,
                "Duration (seconds)": f"{duration_sec:.3f}",
            }
        )

    fieldnames = [
        "Scene_Number",
        "Start_Time (HH:MM:SS.ms)",
        "End_Time (HH:MM:SS.ms)",
        "Duration (seconds)",
    ]
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except OSError as exc:
        print(f"ERROR: Failed to write {csv_path}: {exc}", file=sys.stderr)
        return -1

    print(f"[extract_both] Wrote {csv_path} ({len(rows)} scenes)")
    return len(rows)


def main() -> int:
    root = project_root()
    reference = root / "input" / "reference.mp4"
    raw = root / "input" / "raw_footage.mp4"
    temp = root / "temp"

    print(f"[extract_both] Project root: {root}")

    missing = []
    if not reference.is_file():
        missing.append(str(reference))
    if not raw.is_file():
        missing.append(str(raw))
    if missing:
        print(
            "ERROR: Missing required input video(s):\n  - "
            + "\n  - ".join(missing)
            + "\nPlace reference.mp4 and raw_footage.mp4 under input/ and re-run.",
            file=sys.stderr,
        )
        return 1

    temp.mkdir(parents=True, exist_ok=True)

    ref_count = analyze_video(
        video_path=reference,
        csv_path=temp / "reference_scenes.csv",
        thumbs_dir=temp / "reference_thumbs",
        label="reference",
    )
    if ref_count < 0:
        return 1

    raw_count = analyze_video(
        video_path=raw,
        csv_path=temp / "raw_scenes.csv",
        thumbs_dir=temp / "raw_thumbs",
        label="raw",
    )
    if raw_count < 0:
        return 1

    print(
        f"[extract_both] Done. reference scenes={ref_count}, raw scenes={raw_count}. "
        "Ready for style-transfer matching."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
