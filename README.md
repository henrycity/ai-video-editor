# AI Video Editor — Style Transfer

Match the pacing and visual composition of a short reference Reel/TikTok to a longer raw clip. Local pipeline for M4 Mac.

## Setup

```bash
cd ai-video-editor   # this folder wherever you copied it
# If .cursorrules is missing (store quirk), restore agent rules:
#   mv cursorrules .cursorrules
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires [FFmpeg](https://ffmpeg.org/) on PATH (`brew install ffmpeg`). Use vertical **9:16** raw footage so the lossless render stays vertical.

## Daily workflow

1. Drop the ~1‑minute inspiration clip at `input/reference.mp4`.
2. Drop your longer source at `input/raw_footage.mp4`.
3. In Cursor (Agent), say: **Run the style-transfer edit.**

The agent will:

1. Run `scripts/extract_both.py` (scenes + thumbs for both videos)
2. Match each reference scene’s look to the best raw scene
3. Trim each pick to the **exact reference scene duration**
4. Propose the cut list → wait for your approval
5. Render `output/final_edit.mp4` via `scripts/render_cut.py`

### Manual (optional)

```bash
python scripts/extract_both.py
python scripts/render_cut.py --cuts temp/approved_cuts.json
# or: python scripts/render_cut.py 00:00:01.000 00:00:04.200 …
```
