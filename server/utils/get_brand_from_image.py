import sys
sys.path.append(r"C:\Users\14084\My Closet\GroundingDINO")

import torch
import requests
import os
import cv2
import numpy as np
from PIL import Image
import pytesseract
import torchvision.transforms as T

from groundingdino.util.inference import load_model, predict
from groundingdino.util import box_ops

# === Paths ===
MODEL_CONFIG_PATH = "GroundingDINO/groundingdino/config/GroundingDINO_SwinT_OGC.py"
MODEL_WEIGHTS_PATH = "groundingdino_swint_ogc.pth"

# === Model weights auto-download (skip if already present) ===
if not os.path.exists(MODEL_WEIGHTS_PATH):
    print("⬇️ Downloading Grounding DINO weights...")
    MODEL_WEIGHTS_URL = "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth"
    r = requests.get(MODEL_WEIGHTS_URL)
    with open(MODEL_WEIGHTS_PATH, 'wb') as f:
        f.write(r.content)

# === Load model ===
model = load_model(MODEL_CONFIG_PATH, MODEL_WEIGHTS_PATH)

# === Prompt for tag detection ===
PROMPT = "a clothing tag, neck label, waistband tag"

def detect_tags_and_ocr(image_path):
    print(f"🔍 Processing image: {image_path}")
    image_bgr = cv2.imread(image_path)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    # Convert to torch tensor (0–1, shape [3, H, W])
    transform = T.ToTensor()
    print("📥 Converting to tensor...")
    image_tensor = transform(image_rgb)

    print("🚀 Running prediction...")
    boxes, logits, phrases = predict(  # <-- if it hangs, you'll know it's here
        model=model,
        image=image_tensor,
        caption=PROMPT,
        box_threshold=0.35,
        text_threshold=0.25,
        device="cpu"
    )
    print("✅ Prediction complete.")


    has_text = False

    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = box.astype(int)
        tag_crop = image_rgb[y1:y2, x1:x2]

        gray = cv2.cvtColor(tag_crop, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        text = pytesseract.image_to_string(thresh).strip()
        if text:
            print(f"🧾 Detected text in box {i+1}: {text}")
            has_text = True
        else:
            print(f"📭 No text in box {i+1}")

        # Optional: save cropped tag for debug
        cv2.imwrite(f"tag_{i+1}.jpg", cv2.cvtColor(tag_crop, cv2.COLOR_RGB2BGR))

    if not boxes.any():
        print("❌ No tags detected.")
    elif not has_text:
        print("🕳️ Tag(s) detected, but no readable text found.")
    else:
        print("✅ At least one tag with readable text found.")

# === Run it ===
detect_tags_and_ocr(r"converted_images\img_5134.jpg")


#this script should work and everything is set up but the model takes a lot of power and i dont have a gpu or cuda

#run this script with a powerful gpu and take out the device = "cpu" part 