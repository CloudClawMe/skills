#!/usr/bin/env python3
"""CloudClaw image generation wrapper.

Submits jobs to shared-api/imagegen, polls until completion, downloads and
normalizes each result to the target resolution/aspect-ratio, saves into
--out-dir, and prints a JSON summary on stdout.

Auth is injected transparently by the pod's network layer — no token is
handled here.
"""

import argparse
import base64
import concurrent.futures
import json
import os
import pathlib
import sys
import time
from datetime import datetime
from io import BytesIO

import requests
from PIL import Image

SHARED_API = os.environ.get("SHARED_API", "http://shared-api")
IMAGEGEN_GENERATE = f"{SHARED_API}/imagegen/generate"
IMAGEGEN_JOB = f"{SHARED_API}/imagegen/jobs"

MODE_TARGET_PX = {"1k": 1024, "2k": 2048, "4k": 4096}
MODE_CREDITS = {"1k": 1, "2k": 2, "4k": 8}
MAX_REFS = 4
REF_DOWNSCALE_BYTES = 8 * 1024 * 1024
REF_DOWNSCALE_LONG_PX = 2048
POLL_INITIAL_S = 2.0
POLL_MAX_S = 300.0
POLL_BACKOFF = 1.3
POLL_CAP_S = 10.0
MAX_PARALLEL = 8


def _read_ref(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        r = requests.get(path_or_url, timeout=30)
        r.raise_for_status()
        data = r.content
    else:
        data = pathlib.Path(path_or_url).read_bytes()

    if len(data) > REF_DOWNSCALE_BYTES:
        with Image.open(BytesIO(data)) as img:
            img = img.convert("RGB")
            img.thumbnail((REF_DOWNSCALE_LONG_PX, REF_DOWNSCALE_LONG_PX))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            data = buf.getvalue()
    return base64.b64encode(data).decode("ascii")


def _submit(mode: str, prompt: str, aspect_ratio: str, refs_b64: list) -> str:
    payload = {"mode": mode, "prompt": prompt, "aspect_ratio": aspect_ratio}
    if refs_b64:
        payload["image_urls"] = refs_b64
    r = requests.post(IMAGEGEN_GENERATE, json=payload, timeout=30)
    if r.status_code == 403:
        raise RuntimeError("quota_exceeded")
    r.raise_for_status()
    return r.json()["job_id"]


def _poll(job_id: str) -> dict:
    start = time.time()
    delay = POLL_INITIAL_S
    while time.time() - start < POLL_MAX_S:
        r = requests.get(f"{IMAGEGEN_JOB}/{job_id}", timeout=30)
        r.raise_for_status()
        body = r.json()
        if body.get("status") in ("done", "failed"):
            return body
        time.sleep(delay)
        delay = min(delay * POLL_BACKOFF, POLL_CAP_S)
    return {"status": "failed", "error": "timeout"}


def _target_wh(mode: str, aspect_ratio: str) -> tuple:
    long_side = MODE_TARGET_PX[mode]
    aw, ah = (int(x) for x in aspect_ratio.split(":"))
    if aw >= ah:
        return long_side, round(long_side * ah / aw)
    return round(long_side * aw / ah), long_side


def _normalize(data: bytes, mode: str, aspect_ratio: str) -> tuple:
    target_w, target_h = _target_wh(mode, aspect_ratio)
    target_ratio = target_w / target_h
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGB")
        w, h = img.size
        actual_ratio = w / h
        if abs(actual_ratio - target_ratio) > 0.02:
            if actual_ratio > target_ratio:
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / target_ratio)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))
        img = img.resize((target_w, target_h), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), target_w, target_h


def _classify_error(message: str) -> str:
    m = message.lower()
    if any(t in m for t in ("moderation", "blocked", "policy", "unsafe")):
        return "moderation"
    if "timeout" in m:
        return "timeout"
    return f"provider_error: {message}"


def _process(mode, prompt, aspect_ratio, refs_b64, out_dir, idx, allow_retry=True):
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    try:
        job_id = _submit(mode, prompt, aspect_ratio, refs_b64)
    except RuntimeError as e:
        if str(e) == "quota_exceeded":
            return {"status": "error", "reason": "quota_exceeded"}
        return {"status": "error", "reason": f"provider_error: {e}"}
    except requests.RequestException as e:
        return {"status": "error", "reason": f"provider_error: {e}"}

    body = _poll(job_id)
    if body.get("status") == "failed":
        reason = _classify_error(body.get("error") or "")
        if reason == "moderation" or not allow_retry:
            return {"status": "error", "reason": reason}
        return _process(mode, prompt, aspect_ratio, refs_b64, out_dir, idx, False)

    images = body.get("images") or []
    if not images:
        if allow_retry:
            return _process(mode, prompt, aspect_ratio, refs_b64, out_dir, idx, False)
        return {"status": "error", "reason": "no_output"}

    saved = []
    for i, img in enumerate(images):
        try:
            r = requests.get(img["url"], timeout=60)
            r.raise_for_status()
            data, w, h = _normalize(r.content, mode, aspect_ratio)
        except (requests.RequestException, OSError) as e:
            return {"status": "error", "reason": f"download_failed: {e}"}
        suffix = f"-{i}" if i else ""
        name = f"{ts}-{idx}{suffix}.png"
        path = pathlib.Path(out_dir) / name
        path.write_bytes(data)
        saved.append({"path": str(path), "width": w, "height": h})
    return {"status": "ok", "images": saved}


def main():
    ap = argparse.ArgumentParser(description="CloudClaw image generation wrapper")
    ap.add_argument("--mode", required=True, choices=list(MODE_TARGET_PX))
    ap.add_argument("--prompt", help="Single prompt (use --prompts-file for batch)")
    ap.add_argument("--prompts-file", help="Path to a file with one prompt per line")
    ap.add_argument("--aspect-ratio", default="1:1",
                    help="W:H — e.g. 1:1, 16:9, 9:16, 4:3, 3:4")
    ap.add_argument("--ref", action="append", default=[],
                    help="Reference image (local path or HTTPS URL), repeatable, max 4")
    ap.add_argument("--count", type=int, default=1,
                    help="Generate N identical jobs from --prompt (ignored with --prompts-file)")
    ap.add_argument("--out-dir", default="./images")
    args = ap.parse_args()

    if not args.prompt and not args.prompts_file:
        print(json.dumps({"status": "error", "reason": "missing_prompt"}))
        sys.exit(1)

    if args.prompts_file:
        prompts = [l.strip() for l in pathlib.Path(args.prompts_file).read_text().splitlines() if l.strip()]
    else:
        prompts = [args.prompt] * max(1, args.count)

    if not prompts:
        print(json.dumps({"status": "error", "reason": "empty_prompts"}))
        sys.exit(1)

    refs = args.ref[:MAX_REFS]
    try:
        refs_b64 = [_read_ref(r) for r in refs]
    except (requests.RequestException, OSError) as e:
        print(json.dumps({"status": "error", "reason": f"bad_reference: {e}"}))
        sys.exit(1)

    pathlib.Path(args.out_dir).mkdir(parents=True, exist_ok=True)

    workers = min(MAX_PARALLEL, max(1, len(prompts)))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_process, args.mode, p, args.aspect_ratio, refs_b64, args.out_dir, i)
            for i, p in enumerate(prompts)
        ]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    ok = [r for r in results if r.get("status") == "ok"]
    errors = [r for r in results if r.get("status") == "error"]
    images = [img for r in ok for img in r["images"]]
    credits = MODE_CREDITS[args.mode] * len(images)

    if not ok and errors:
        print(json.dumps({"status": "error", "reason": errors[0]["reason"]}, indent=2))
        sys.exit(2)

    print(json.dumps({
        "status": "ok" if not errors else "partial",
        "mode": args.mode,
        "images": images,
        "credits_charged": credits,
        "errors": [e["reason"] for e in errors],
    }, indent=2))


if __name__ == "__main__":
    main()
