import base64
import io
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ASSET_DIR = BASE_DIR / "assets"
RESULT_DIR = BASE_DIR / "results"
RESULT_DIR.mkdir(exist_ok=True)

FASHN_API_KEY = os.getenv("FASHN_API_KEY", "")
FASHN_API_BASE = os.getenv("FASHN_API_BASE", "https://api.fashn.ai/v1").rstrip("/")
DEFAULT_RESOLUTION = os.getenv("DEFAULT_RESOLUTION", "2k")
DEFAULT_GENERATION_MODE = os.getenv("DEFAULT_GENERATION_MODE", "balanced")

MODEL_IMAGES = {
    "boy": ASSET_DIR / "boy_uniform.png",
    "girl": ASSET_DIR / "girl_uniform.png",
}
BACKGROUND_IMAGE = ASSET_DIR / "hansin_background.png"

app = FastAPI(title="Hansin FASHN Booth")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=ASSET_DIR), name="assets")
app.mount("/results", StaticFiles(directory=RESULT_DIR), name="results")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "has_api_key": bool(FASHN_API_KEY),
        "resolution": DEFAULT_RESOLUTION,
        "generation_mode": DEFAULT_GENERATION_MODE,
    }


@app.post("/api/generate")
async def generate(
    photo: UploadFile = File(...),
    gender: str = Form("boy"),
    refine: str = Form("true"),
) -> JSONResponse:
    if not FASHN_API_KEY:
        raise HTTPException(status_code=500, detail="FASHN_API_KEY가 설정되지 않았습니다.")
    if gender not in MODEL_IMAGES:
        raise HTTPException(status_code=400, detail="gender는 boy 또는 girl 이어야 합니다.")

    raw = await photo.read()
    if not raw:
        raise HTTPException(status_code=400, detail="사진 파일이 비어 있습니다.")

    refine_bool = str(refine).lower() in {"1", "true", "yes", "on"}

    try:
        student_bytes = normalize_image_bytes(raw)
        result_bytes, debug_info = await generate_with_fashn(student_bytes, gender, refine_bool)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"생성 중 오류가 발생했습니다: {e}")

    file_id = str(uuid.uuid4())
    out_path = RESULT_DIR / f"{file_id}.jpg"
    out_path.write_bytes(result_bytes)
    cleanup_old_files(RESULT_DIR, max_age_seconds=60 * 60 * 12)

    return JSONResponse(
        {
            "ok": True,
            "image_url": f"/results/{file_id}.jpg",
            "debug": debug_info,
        }
    )


async def generate_with_fashn(student_bytes: bytes, gender: str, refine: bool) -> tuple[bytes, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        student_data_uri = bytes_to_data_uri(student_bytes, mime="image/jpeg")
        base_model_uri = file_to_data_uri(MODEL_IMAGES[gender])
        background_uri = file_to_data_uri(BACKGROUND_IMAGE)

        swap_prompt = (
            "Replace the model identity with the face reference while keeping the elementary school uniform exactly intact. "
            "Preserve a neat child-friendly appearance, realistic proportions, a clean hairstyle, and a natural school-photo look. "
            "Keep the person standing and facing the camera in a tidy, polished way."
        )

        swap_payload = {
            "model_name": "model-swap",
            "inputs": {
                "model_image": base_model_uri,
                "face_reference": student_data_uri,
                "face_reference_mode": "match_reference",
                "prompt": swap_prompt,
                "resolution": DEFAULT_RESOLUTION,
                "generation_mode": DEFAULT_GENERATION_MODE,
                "num_images": 1,
                "output_format": "jpeg",
                "return_base64": True,
            },
        }

        swap_id = await start_prediction(client, swap_payload)
        swap_status = await poll_prediction(client, swap_id)
        swap_image = await resolve_status_output_as_bytes(client, swap_status)

        debug_info: dict[str, Any] = {"swap_id": swap_id}

        if not refine:
            return swap_image, debug_info

        edit_prompt = (
            "Place the student naturally in front of the provided Hansin Elementary School entrance and playground background. "
            "Preserve the student's identity, hairstyle, facial features, and the same school uniform details. "
            "Blend the hairline, neck, ears, and shoulders naturally so the result looks like one coherent real photograph. "
            "Match outdoor daylight lighting, realistic shadows, and correct perspective. "
            "The final result should look like a polished school promotional photo, not a pasted collage."
        )

        edit_payload = {
            "model_name": "edit",
            "inputs": {
                "image": bytes_to_data_uri(swap_image, mime="image/jpeg"),
                "image_context": background_uri,
                "prompt": edit_prompt,
                "resolution": DEFAULT_RESOLUTION,
                "generation_mode": DEFAULT_GENERATION_MODE,
                "num_images": 1,
                "output_format": "jpeg",
                "return_base64": True,
            },
        }

        edit_id = await start_prediction(client, edit_payload)
        edit_status = await poll_prediction(client, edit_id)
        edit_image = await resolve_status_output_as_bytes(client, edit_status)
        debug_info["edit_id"] = edit_id
        return edit_image, debug_info


async def start_prediction(client: httpx.AsyncClient, payload: dict[str, Any]) -> str:
    resp = await client.post(
        f"{FASHN_API_BASE}/run",
        headers={
            "Authorization": f"Bearer {FASHN_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
    )
    if resp.status_code >= 400:
        raise HTTPException(status_code=500, detail=f"FASHN run 요청 실패: {resp.text}")
    data = resp.json()
    prediction_id = data.get("id")
    if not prediction_id:
        raise HTTPException(status_code=500, detail=f"예측 ID를 받지 못했습니다: {data}")
    return prediction_id


async def poll_prediction(client: httpx.AsyncClient, prediction_id: str, timeout_seconds: int = 240) -> dict[str, Any]:
    start = time.time()
    last_payload: dict[str, Any] | None = None
    while time.time() - start < timeout_seconds:
        resp = await client.get(
            f"{FASHN_API_BASE}/status/{prediction_id}",
            headers={"Authorization": f"Bearer {FASHN_API_KEY}"},
        )
        if resp.status_code >= 400:
            raise HTTPException(status_code=500, detail=f"FASHN status 요청 실패: {resp.text}")

        payload = resp.json()
        last_payload = payload
        status = payload.get("status")
        if status == "completed":
            return payload
        if status == "failed":
            raise HTTPException(status_code=500, detail=f"FASHN 생성 실패: {payload.get('error')}")
        await sleep_async(2.5)

    raise HTTPException(status_code=500, detail=f"시간 초과: 마지막 상태={last_payload}")


async def resolve_status_output_as_bytes(client: httpx.AsyncClient, status_payload: dict[str, Any]) -> bytes:
    output = status_payload.get("output")
    if not output:
        raise HTTPException(status_code=500, detail=f"출력 이미지가 없습니다: {status_payload}")

    if isinstance(output, list):
        item = output[0]
    else:
        item = output

    if isinstance(item, dict):
        # defensive handling for possible alternate schemas
        item = item.get("url") or item.get("image") or item.get("base64")

    if not isinstance(item, str):
        raise HTTPException(status_code=500, detail="출력 형식을 해석할 수 없습니다.")

    if item.startswith("data:image/"):
        _, b64 = item.split(",", 1)
        return base64.b64decode(b64)
    if item.startswith("http://") or item.startswith("https://"):
        resp = await client.get(item)
        if resp.status_code >= 400:
            raise HTTPException(status_code=500, detail=f"결과 이미지 다운로드 실패: {resp.text}")
        return resp.content
    if item == "<base64>_expired":
        raise HTTPException(status_code=500, detail="FASHN base64 출력이 만료되었습니다.")

    # raw base64 without data URI prefix
    try:
        return base64.b64decode(item)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"출력 해석 실패: {e}")


def normalize_image_bytes(raw: bytes, max_side: int = 1536, quality: int = 92) -> bytes:
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def file_to_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return bytes_to_data_uri(path.read_bytes(), mime=mime)


def bytes_to_data_uri(data: bytes, mime: str) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def cleanup_old_files(folder: Path, max_age_seconds: int = 3600) -> None:
    now = time.time()
    for p in folder.glob("*"):
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_seconds:
                p.unlink(missing_ok=True)
        except Exception:
            pass


async def sleep_async(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
