import io
import time
import logging

from picamera2 import Picamera2

from summer_toolkit.utility.singleton import Singleton

logger = loggging.getLogger(__name__)

class CameraAgent(metaclass=Singleton):
    def __init__(self):
        try:
            self.camera = Picamera2()
            self.camera_still_config = self.camera.create_still_configuration(
                main={'size': (1024, 768)}
            )
            self.camera.configure(self.camera_still_config)
            self.camera.start()
            time.sleep(1) #카메라 안정화 대기
            logger.info("Camera successfully initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize camera:{e}")
            self.camera = None

    def capture(self, is_bytearray=True):
        if not self.camera:
            logger.error("Camera is not initialized.")
            return None
        
        #하드웨어 캡쳐 수행
        captured = self.camera.capture_image('main')

        if is_bytearray:
            result = io.BytesIO()
            #포맷 및 품질 설정을 통해 속도 조절 가능
            captured.save(result, format='jpeg')

            return result.getvalue()

        return captured
    
    def stop(self):
        if self.camera:
            self.camera.stop()
            logger.info("Camera stopped.")
