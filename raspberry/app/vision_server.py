"""Microservice Vision haute disponibilité pour Raspberry Pi 5 / Rafiki.

Caractéristiques :
- Capture vidéo en arrière-plan multi-threadée (latence < 5 ms sur /capture).
- Reconnexion automatique si la caméra USB / V4L2 / CSI est déconnectée ou gelée.
- Endpoints compatibles :
    - GET /health         : État du capteur et télémétrie.
    - GET /capture        : Renvoie l'image JPEG binaire instantanée.
    - GET /capture/json   : Renvoie l'image encodée en Base64 JSON.
    - POST /api/register  : Auto-inscription auprès du serveur cerveau Rafiki (PC).
"""

from __future__ import annotations

import argparse
import base64
import logging
import threading
import time
import urllib.request
from typing import Optional

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from fastapi import FastAPI, HTTPException, Response
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    FastAPI = None
    uvicorn = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [VisionServer] %(message)s",
)
logger = logging.getLogger("vision_server")


class ThreadedCamera:
    """Lecteur de caméra multi-threadé avec reconnexion automatique."""

    def __init__(
        self,
        device_index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 20,
    ) -> None:
        self.device_index = device_index
        self.width = width
        self.height = height
        self.fps = fps
        self.cap = None
        self.lock = threading.Lock()
        self.running = False
        self.latest_frame = None
        self.latest_jpeg: Optional[bytes] = None
        self.last_capture_time = 0.0
        self.consecutive_errors = 0
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if cv2 is None:
            logger.error("OpenCV (cv2) n'est pas installé.")
            return
        self.running = True
        self._init_camera()
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        logger.info("Thread de capture vidéo démarré sur le périphérique %d", self.device_index)

    def _init_camera(self) -> bool:
        if cv2 is None:
            return False
        with self.lock:
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None

            try:
                # Utiliser V4L2 sous Linux pour une vitesse maximale
                self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_V4L2)
                if not self.cap.isOpened():
                    self.cap = cv2.VideoCapture(self.device_index)

                if self.cap.isOpened():
                    self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                    self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    logger.info("Caméra %d ouverte avec succès.", self.device_index)
                    self.consecutive_errors = 0
                    return True
                else:
                    logger.warning("Impossible d'ouvrir la caméra %d.", self.device_index)
                    return False
            except Exception as exc:
                logger.error("Erreur lors de l'initialisation de la caméra: %s", exc)
                return False

    def _capture_loop(self) -> None:
        delay = 1.0 / max(1, self.fps)
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(1.0)
                self._init_camera()
                continue

            try:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    # Encodage JPEG immédiat
                    success, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if success:
                        with self.lock:
                            self.latest_frame = frame
                            self.latest_jpeg = jpeg.tobytes()
                            self.last_capture_time = time.time()
                            self.consecutive_errors = 0
                else:
                    self.consecutive_errors += 1
                    if self.consecutive_errors > 15:
                        logger.warning("Caméra ne produit plus de frames. Reconnexion...")
                        self._init_camera()
                        time.sleep(1.0)
            except Exception as exc:
                logger.error("Exception dans la boucle vidéo: %s", exc)
                time.sleep(0.5)

            time.sleep(delay)

    def get_jpeg(self) -> Optional[bytes]:
        with self.lock:
            return self.latest_jpeg

    def is_alive(self) -> bool:
        with self.lock:
            return bool(
                self.latest_jpeg is not None
                and (time.time() - self.last_capture_time) < 3.0
            )

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        with self.lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None


camera_instance: Optional[ThreadedCamera] = None


def create_app(camera: ThreadedCamera) -> FastAPI:
    if FastAPI is None:
        raise RuntimeError("FastAPI n'est pas installé.")

    app = FastAPI(title="Rafiki Raspberry Pi Vision Service", version="2.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    def index():
        return {
            "service": "Rafiki Vision Service",
            "status": "online",
            "camera_ready": camera.is_alive(),
        }

    @app.get("/health")
    def health():
        return {
            "status": "online",
            "device_name": "RaspberryPi-Vision-01",
            "camera_type": "opencv_v4l2",
            "is_active": camera.is_alive(),
            "last_capture_age_seconds": round(time.time() - camera.last_capture_time, 2)
            if camera.last_capture_time > 0
            else None,
            "settings": {
                "width": camera.width,
                "height": camera.height,
                "fps": camera.fps,
                "format": "jpeg",
            },
        }

    @app.get("/capture")
    def capture_binary():
        jpeg = camera.get_jpeg()
        if not jpeg:
            raise HTTPException(status_code=503, detail="Aucune frame disponible.")
        return Response(content=jpeg, media_type="image/jpeg")

    @app.get("/capture/json")
    def capture_json():
        jpeg = camera.get_jpeg()
        if not jpeg:
            raise HTTPException(status_code=503, detail="Aucune frame disponible.")
        encoded = base64.b64encode(jpeg).decode("ascii")
        return {
            "status": "ok",
            "image_base64": encoded,
            "data_uri": f"data:image/jpeg;base64,{encoded}",
            "timestamp": time.time(),
            "width": camera.width,
            "height": camera.height,
        }

    return app


def register_to_brain(brain_url: str, vision_host: str, vision_port: int) -> None:
    """Enregistre automatiquement ce service de vision auprès du PC Rafiki."""
    clean_brain = brain_url.rstrip("/")
    my_url = f"http://{vision_host}:{vision_port}"
    try:
        req = urllib.request.Request(
            f"{clean_brain}/api/vision/register",
            data=f'{{"vision_url": "{my_url}"}}'.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                logger.info("Service vision enregistré avec succès auprès du cerveau: %s", clean_brain)
    except Exception as exc:
        logger.warning("Impossible d'auto-enregistrer la vision auprès du cerveau (%s): %s", clean_brain, exc)


def main():
    parser = argparse.ArgumentParser(description="Serveur Vision Haute Disponibilité Raspberry Pi")
    parser.add_argument("--host", default="0.0.0.0", help="Hôte d'écoute")
    parser.add_argument("--port", type=int, default=8000, help="Port d'écoute")
    parser.add_argument("--device", type=int, default=0, help="Index de la caméra (/dev/videoX)")
    parser.add_argument("--width", type=int, default=1280, help="Largeur de capture")
    parser.add_argument("--height", type=int, default=720, help="Hauteur de capture")
    parser.add_argument("--fps", type=int, default=20, help="Images par seconde")
    parser.add_argument("--brain-url", default="", help="URL du cerveau PC (ex: http://10.20.20.175:7860)")

    args = parser.parse_args()

    brain_url = args.brain_url.strip()
    if not brain_url:
        import sys
        from pathlib import Path
        repo_root = Path(__file__).resolve().parent.parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
            
        from shared.discovery import discover_brain_url
        discovered = discover_brain_url()
        if discovered:
            brain_url = discovered
            print(f"Cerveau trouve par decouverte auto : {brain_url}")
        else:
            print("Aucun cerveau trouve par decouverte auto. Enregistrement ignore.")

    camera = ThreadedCamera(
        device_index=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
    )
    camera.start()

    if brain_url:
        threading.Thread(
            target=lambda: (time.sleep(2.0), register_to_brain(brain_url, args.host, args.port)),
            daemon=True,
        ).start()

    app = create_app(camera)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        camera.stop()


if __name__ == "__main__":
    main()
