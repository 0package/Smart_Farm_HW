from fastapi import APIRouter, Request, Response, BackgroundTasks
from fastapi.responses import StreamingResponse
from picamera2 import Picamera2

from rfp.monitor.camera_agent import CameraAgent

from fastapi import UploadFile, File, HTTPException
import os
from datetime import datetime
import requests
import logging

from config import SERVER_URL

monitor_router = APIRouter(tags=['monitor'], prefix='/monitor')
camera_agent = CameraAgent()
logger = logging.getLogger(__name__)

#클라우드 업로드 전용 백그라운드 함수
def upload_to_cloud_task(farm_id:int, img_bytes:bytes):
    url = f"{SERVER_URL}/upload-image?farmId={farm_id}"
    files = {'file':('cpature.jpg', img_bytes, 'image/jpeg')}
    try:
        response = requests.post(url, files=files, timeout=10)
        logger.info(f"Cloud upload successful:{response.status_code}")
    except Exception as e:
        logger.error(f"Cloud upload failed: {e}")

# 비동기 제너레이터로 변경하여 스트리밍 효율 향상
async def generate_image():
    while True:
        # 카메라 캡쳐는 CPU/하드웨어 작업이므로 스레드 풀에서 실행하는 것이 좋으나,
        # picamera2 라이브러리 특성에 따라 직접 호출
        img_bytes = camera_agent.capture()
        if img_bytes:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + img_bytes + b'\r\n\r\n'
            )
        #루프 사이의 아주 짧은 대기로 CPU 점유율 조절
        await asyncio.sleep(0.1)


@monitor_router.get('', include_in_schema=False)
def respond_root(request: Request):
    return StreamingResponse(
        generate_image(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )

@monitor_router.get("/snapshot")
async def take_snapshot(farm_id: int, background_tasks:BackgroundTasks):
    img_bytes = camera_agent.capture()
    if not img_bytes:
        return Response(content="Camera Error", status_code=500)
    background_tasks.add_task(upload_to_cloud_task, farm_id, img_bytes)
    
    return Response(content=img_bytes, media_type="image/jpeg")
    #try:
    #    save_dir = "uploaded_images"
    #    os.makedirs(save_dir, exist_ok=True)
    #    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    #    file_path = os.path.join(save_dir, f"{timestamp}_{file.filename}")

    #    with open(file_path, "wb") as buffer:
    #        buffer.write(await file.read())

    #    return {"message": "image upload complete", "file_path": file_path}
    #except Exception as e:
    #    raise HTTPException(status_code=500, detail=str(e))

