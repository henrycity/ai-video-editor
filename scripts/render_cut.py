#!/usr/bin/env python3
"""Losslessly extract approved cuts from raw_footage.mp4 and concat into final_edit.mp4."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import ffmpeg


def project_root() -> Path:
    """Project root = parent of scripts/."""
    return Path(__file__).resolve().parent.parent


def ensure_ffmpeg_binary() -> None:
    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "ERROR: ffmpeg binary not found on PATH.\n"
            "  Install it (e.g. `brew install ffmpeg` on macOS) and retry."
        )


def parse_cuts_from_json(path: Path) -> list[tuple[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"ERROR: Failed to read cuts JSON ({path}): {exc}") from exc

    if not isinstance(data, list):
        raise SystemExit("ERROR: Cuts JSON must be a list of {start, end} objects.")

    cuts: list[tuple[str, str]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise SystemExit(f"ERROR: Cut #{i + 1} is not an object: {item!r}")
        start = item.get("start")
        end = item.get("end")
        if not start or not end:
            raise SystemExit(
                f"ERROR: Cut #{i + 1} needs non-empty 'start' and 'end' strings: {item!r}"
            )
        cuts.append((str(start), str(end)))
    return cuts


def parse_cuts_from_pairs(values: list[str]) -> list[tuple[str, str]]:
    if len(values) % 2 != 0:
        raise SystemExit(
            "ERROR: Positional timestamps must be start/end pairs "
            "(even number of arguments).\n"
            "  Example: 00:00:01.000 00:00:05.500 00:00:10.000 00:00:14.000"
        )
    return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]


def escape_concat_path(path: Path) -> str:
    """Escape a path for FFmpeg concat demuxer 'file' lines."""
    text = str(path.resolve())
    return text.replace("'", "'\\''")


def write_concat_list(concat_path: Path, chunk_paths: list[Path]) -> None:
    lines = [f"file '{escape_concat_path(p)}'" for p in chunk_paths]
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cleanup(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                print(f"[render_cut] Cleaned up {path}")
        except OSError as exc:
            print(f"WARNING: Could not delete {path}: {exc}", file=sys.stderr)


def extract_chunk(
    video_path: Path,
    start: str,
    end: str,
    out_path: Path,
) -> None:
    """Lossless extract [start, end) via stream copy (preserves 9:16 + audio)."""
    print(f"[render_cut] Extracting {start} → {end} → {out_path.name}")
    try:
        (
            ffmpeg.input(str(video_path), ss=start, to=end)
            .output(str(out_path), c="copy")
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as exc:
        stderr = ""
        if getattr(exc, "stderr", None):
            stderr = exc.stderr.decode("utf-8", errors="replace")
        raise SystemExit(
            f"ERROR: FFmpeg failed extracting {start}–{end}.\n{stderr}"
        ) from exc


def concat_chunks(concat_path: Path, output_path: Path) -> None:
    """
    Concat with -c copy (no re-encode).
    Aspect ratio is preserved from the source streams — use 9:16 raw_footage
    so the final_edit stays vertical without scaling.
    """
    print(f"[render_cut] Concatenating (stream copy, aspect preserved) → {output_path}")
    try:
        (
            ffmpeg.input(str(concat_path), format="concat", safe=0)
            .output(str(output_path), c="copy")
            .overwrite_output()
            .run(quiet=True)
        )
    except ffmpeg.Error as exc:
        stderr = ""
        if getattr(exc, "stderr", None):
            stderr = exc.stderr.decode("utf-8", errors="replace")
        raise SystemExit(f"ERROR: FFmpeg concat failed.\n{stderr}") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Losslessly cut and stitch clips from input/raw_footage.mp4 "
            "into output/final_edit.mp4 (stream copy preserves 9:16 + audio)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/render_cut.py --cuts temp/approved_cuts.json\n"
            "  python scripts/render_cut.py 00:00:01.000 00:00:05.500 "
            "00:00:10.000 00:00:14.000\n"
            "\n"
            "JSON format:\n"
            '  [{"start": "00:00:01.000", "end": "00:00:05.500"}, ...]\n'
            "\n"
            "Tip: each cut's duration should match the corresponding reference "
            "scene Duration from temp/reference_scenes.csv.\n"
        ),
    )
    parser.add_argument(
        "--cuts",
        type=Path,
        metavar="FILE",
        help="JSON file with a list of {start, end} timestamp objects.",
    )
    parser.add_argument(
        "timestamps",
        nargs="*",
        help="Optional start/end pairs as positional args (HH:MM:SS.ms).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    root = project_root()
    video_path = root / "input" / "raw_footage.mp4"
    output_dir = root / "output"
    temp_dir = root / "temp"
    output_path = output_dir / "final_edit.mp4"
    concat_path = temp_dir / "concat.txt"

    print(f"[render_cut] Project root: {root}")
    ensure_ffmpeg_binary()

    if not video_path.is_file():
        print(
            f"ERROR: Missing input video.\n  Expected: {video_path}",
            file=sys.stderr,
        )
        return 1

    cuts: list[tuple[str, str]] = []
    if args.cuts is not None:
        cuts_path = args.cuts if args.cuts.is_absolute() else root / args.cuts
        print(f"[render_cut] Loading cuts from {cuts_path}")
        cuts.extend(parse_cuts_from_json(cuts_path))
    if args.timestamps:
        print("[render_cut] Loading cuts from positional timestamp pairs")
        cuts.extend(parse_cuts_from_pairs(args.timestamps))

    if not cuts:
        print(
            "ERROR: Empty cut list. Provide --cuts FILE and/or start/end timestamp pairs.",
            file=sys.stderr,
        )
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    print(f"[render_cut] {len(cuts)} cut(s) queued from raw_footage.mp4.")
    chunk_paths: list[Path] = []
    temp_artifacts: list[Path] = []

    try:
        for i, (start, end) in enumerate(cuts, start=1):
            chunk = temp_dir / f"chunk_{i:03d}.mp4"
            extract_chunk(video_path, start, end, chunk)
            chunk_paths.append(chunk)
            temp_artifacts.append(chunk)

        write_concat_list(concat_path, chunk_paths)
        temp_artifacts.append(concat_path)
        print(f"[render_cut] Wrote concat list: {concat_path}")

        concat_chunks(concat_path, output_path)

        if not output_path.is_file() or output_path.stat().st_size == 0:
            print(f"ERROR: Output missing or empty: {output_path}", file=sys.stderr)
            return 1

        print(f"[render_cut] Success → {output_path}")
        print(
            "[render_cut] Note: -c copy preserves source aspect; "
            "use vertical 9:16 raw_footage for a vertical final_edit."
        )
        cleanup(temp_artifacts)
        print("[render_cut] Done.")
        return 0
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Unexpected failure: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
