#same script as below yolo_tag_ocr.py in back_tag_detector folder but now just making it callable 

import os
import cv2
import torch
import numpy as np
from ultralytics import YOLO
import easyocr
from PIL import Image
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

# === Path Setup ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DETECTOR_DIR = os.path.join(BASE_DIR, "back_tag_detector")

MODEL_PATH = os.path.join(DETECTOR_DIR, "runs", "detect", "train2", "weights", "best.pt")
SR_MODEL_PATH = os.path.join(DETECTOR_DIR, "RealESRGAN_x4plus.pth")
PADDING = 20

# === Load Models ===
yolo_model = YOLO(MODEL_PATH)
reader = easyocr.Reader(['en'], gpu=torch.cuda.is_available())

model_sr = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
upsampler = RealESRGANer(
    scale=4,
    model_path=SR_MODEL_PATH,
    model=model_sr,
    tile=0,
    tile_pad=10,
    pre_pad=0,
    half=False,
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
)

# === Main OCR Function ===
def extract_tag_text(image_path):
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
