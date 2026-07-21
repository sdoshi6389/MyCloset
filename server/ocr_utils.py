#same script as below yolo_tag_ocr.py in back_tag_detector folder but now just making it callable

import os
import cv2

# === Path Setup ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DETECTOR_DIR = os.path.join(BASE_DIR, "back_tag_detector")

MODEL_PATH = os.environ.get("TAG_YOLO_MODEL") or os.path.join(
    DETECTOR_DIR, "runs", "detect", "train2", "weights", "best.pt"
)
SR_MODEL_PATH = os.environ.get("REALESRGAN_MODEL") or os.path.join(
    DETECTOR_DIR, "RealESRGAN_x4plus.pth"
)
PADDING = 20

# === Lazy, guarded model loading ===
# Heavy models (YOLO tag detector + EasyOCR + RealESRGAN) load on the first
# extract_tag_text() call, not at import. If the tag-detector weights (best.pt)
# or RealESRGAN weights aren't present — e.g. not yet staged on the deploy
# volume — tag OCR is disabled gracefully instead of crashing the whole app at
# import time (closet.py imports this module at boot).
_OCR = {"tried": False, "yolo": None, "reader": None, "upsampler": None}


def _ensure_ocr_models() -> bool:
    if _OCR["tried"]:
        return _OCR["yolo"] is not None
    _OCR["tried"] = True
    try:
        import _compat  # noqa: F401  — torchvision.functional_tensor shim for basicsr
        import torch
        from ultralytics import YOLO
        import easyocr
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet

        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"tag-detector model not found: {MODEL_PATH}")

        _OCR["yolo"] = YOLO(MODEL_PATH)
        _OCR["reader"] = easyocr.Reader(["en"], gpu=torch.cuda.is_available())

        model_sr = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                           num_block=23, num_grow_ch=32, scale=4)
        _OCR["upsampler"] = RealESRGANer(
            scale=4, model_path=SR_MODEL_PATH, model=model_sr,
            tile=0, tile_pad=10, pre_pad=0, half=False,
            device=torch.device("cuda" if torch.cuda.is_available() else "cpu"),
        )
        print("✅ Tag-OCR models loaded")
        return True
    except Exception as e:
        print(f"⚠️  Tag-OCR models unavailable — tag reading disabled: {e}")
        _OCR["yolo"] = None
        return False


# === Main OCR Function ===
def extract_tag_text(image_path):
    if not _ensure_ocr_models():
        return None

    yolo_model = _OCR["yolo"]
    reader = _OCR["reader"]
    upsampler = _OCR["upsampler"]

    image = cv2.imread(image_path)
    results = yolo_model(image_path)[0]

    if results.boxes is None or len(results.boxes.data) == 0:
        return None

    for box in results.boxes.data:
        x1, y1, x2, y2, *_ = box.tolist()
        x1, y1 = max(int(x1) - PADDING, 0), max(int(y1) - PADDING, 0)
        x2, y2 = min(int(x2) + PADDING, image.shape[1]), min(int(y2) + PADDING, image.shape[0])
        cropped = image[y1:y2, x1:x2]

        # Try OCR on cropped
        results_cropped = reader.readtext(cropped)
        if results_cropped:
            return results_cropped[0][1]

        # Try on super-res version
        try:
            sr_image_np, _ = upsampler.enhance(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB), outscale=1)
            sr_results = reader.readtext(sr_image_np)
            if sr_results:
                return sr_results[0][1]
        except Exception:
            pass

        break  # Only first detected tag

    return None
