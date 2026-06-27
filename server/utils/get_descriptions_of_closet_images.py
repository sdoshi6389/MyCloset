import os
import csv
from PIL import Image
from transformers import InstructBlipProcessor, InstructBlipForConditionalGeneration
import torch

# === Load InstructBLIP model ===
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"🧠 Using device: {device}")

print("📦 Loading InstructBLIP Vicuna 7B model...")
processor = InstructBlipProcessor.from_pretrained("Salesforce/instructblip-vicuna-7b")
model = InstructBlipForConditionalGeneration.from_pretrained("Salesforce/instructblip-vicuna-7b").to(device)

# === Config ===
IMAGE_FOLDER = "converted_images"  # Folder with your clothing images
OUTPUT_CSV = "instructblip_clothing_captions.csv"

# 👇 You can give detailed GPT-style prompts here!
PROMPT = (
    "Describe the clothing item in detail, including color, type, style, material, fit, and any text or graphics."
)

# === Captioning Function ===
def generate_caption(image_path):
    try:
        image = Image.open(image_path).convert("RGB")

        inputs = processor(images=image, text=PROMPT, return_tensors="pt").to(device)

        output = model.generate(
            **inputs,
            max_length=256,
            num_beams=5,
            repetition_penalty=1.5,
            length_penalty=1.0,
            early_stopping=True
        )

        caption = processor.decode(output[0], skip_special_tokens=True).strip()
        return caption

    except Exception as e:
        print(f"❌ Error processing {image_path}: {e}")
        return "ERROR"

# === Main Loop ===
def caption_all_images():
    results = []
    print(f"🖼️ Scanning folder: {IMAGE_FOLDER}")
    for filename in sorted(os.listdir(IMAGE_FOLDER)):
        if filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            path = os.path.join(IMAGE_FOLDER, filename)
            try:
                print(f"🧠 Captioning: {filename}...")
                caption = generate_caption(path)
                print(f"   📌 {caption}")
                results.append((filename, caption))
            except Exception as e:
                print(f"❌ Failed on {filename}: {e}")
                results.append((filename, "ERROR"))

    # Save to CSV
    print(f"\n📝 Saving results to {OUTPUT_CSV}...")
    with open(OUTPUT_CSV, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "caption"])
        writer.writerows(results)

    print("✅ All captions saved!")

# === Run Script ===
if __name__ == "__main__":
    caption_all_images()



#this should work but needs a gpu machine, try this out when have access to one with over (12 gb ram as well, have at least 64 gb ram when trying it)