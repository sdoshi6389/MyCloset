import cv2
import numpy as np
from ultralytics import YOLO
import easyocr
from PIL import Image
import torch
from realesrgan import RealESRGANer
from basicsr.archs.rrdbnet_arch import RRDBNet

# === Config ===
IMAGE_PATH = "test_tag.jpg"
MODEL_PATH = "runs/detect/train2/weights/best.pt"
CROP_OUTPUT = "cropped_tag.jpg"
UPSCALED_OUTPUT = "upscaled_tag.jpg"
SR_MODEL_PATH = "RealESRGAN_x4plus.pth"
PADDING = 20

# === Load YOLOv8 and detect ===
model = YOLO(MODEL_PATH)
results = model(IMAGE_PATH)[0]
image = cv2.imread(IMAGE_PATH)

if results.boxes is None or len(results.boxes.data) == 0:
    print("❌ No back_tag detected.")
    exit()

for box in results.boxes.data:
    x1, y1, x2, y2, conf, cls = box.tolist()
    x1 = max(int(x1) - PADDING, 0)
    y1 = max(int(y1) - PADDING, 0)
    x2 = min(int(x2) + PADDING, image.shape[1])
    y2 = min(int(y2) + PADDING, image.shape[0])

    # === Crop tag
    cropped = image[y1:y2, x1:x2]
    cv2.imwrite(CROP_OUTPUT, cropped)

    print("🔍 Running EasyOCR on CROPPED tag...")
    reader = easyocr.Reader(['en'], gpu=torch.cuda.is_available())
    results_cropped = reader.readtext(cropped)

    print("\n🧠 OCR Output (Cropped):")
    if not results_cropped:
        print("❌ No text detected in cropped image.")
    else:
        for bbox, text, conf in results_cropped:
            print(f"🅰️ '{text}' (conf: {conf:.2f})")

    # === Super-resolution
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    model_sr = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                       num_block=23, num_grow_ch=32, scale=4)

    upsampler = RealESRGANer(
        scale=4,
        model_path=SR_MODEL_PATH,
        model=model_sr,
        tile=0,
        tile_pad=10,
        pre_pad=0,
        half=False,
        device=device
    )

    img_np = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)

    try:
        sr_image_np, _ = upsampler.enhance(img_np, outscale=1)
        sr_pil = Image.fromarray(sr_image_np)
        sr_pil.save(UPSCALED_OUTPUT)

        print("\n🔍 Running EasyOCR on UPSCALED tag...")
        sr_cv2 = cv2.imread(UPSCALED_OUTPUT)
        results_sr = reader.readtext(sr_cv2)

        print("\n🧠 OCR Output (Upscaled):")
        if not results_sr:
            print("❌ No text detected in upscaled image.")
        else:
            for bbox, text, conf in results_sr:
                print(f"🅰️ '{text}' (conf: {conf:.2f})")

    except Exception as e:
        print(f"❌ RealESRGAN super-resolution failed: {e}")
        print("⚠️ Skipping OCR on upscaled image.")

    break  # Only process the first tag

print("\n✅ Done. OCR for both cropped and enhanced tags complete.")
