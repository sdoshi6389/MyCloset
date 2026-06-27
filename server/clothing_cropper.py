from ultralytics import YOLO
import cv2
import os
from PIL import Image

# === Configuration ===
YOLO_MODEL_PATH = "yolov8n.pt"  # use yolov8n.pt or yolov8s.pt for general object detection
INPUT_IMAGE = "test_images/test_tag4.jpg"
OUTPUT_CROP_DIR = "cropped_clothing"
CONFIDENCE_THRESHOLD = 0.3

# === Class names for COCO that refer to clothing ===
CLOTHING_CLASSES = {
    0: "person",
    17: "cat", 18: "dog", 19: "horse", 20: "sheep", 21: "cow", 22: "elephant", 23: "bear", 24: "zebra", 25: "giraffe",
    26: "backpack", 27: "umbrella", 28: "handbag", 29: "tie", 30: "suitcase", 31: "frisbee", 32: "skis", 33: "snowboard",
    34: "sports ball", 35: "kite", 36: "baseball bat", 37: "baseball glove", 38: "skateboard", 39: "surfboard",
    40: "tennis racket", 41: "bottle", 42: "wine glass", 43: "cup", 44: "fork", 45: "knife", 46: "spoon", 47: "bowl",
    52: "banana", 53: "apple", 54: "sandwich", 55: "orange", 56: "broccoli", 57: "carrot", 58: "hot dog", 59: "pizza",
    60: "donut", 61: "cake", 62: "chair", 63: "couch", 64: "potted plant", 65: "bed", 67: "dining table", 69: "toilet",
    71: "tv", 72: "laptop", 73: "mouse", 74: "remote", 75: "keyboard", 76: "cell phone", 77: "microwave", 78: "oven",
    79: "toaster", 80: "sink", 81: "refrigerator", 82: "book", 83: "clock", 84: "vase", 85: "scissors", 86: "teddy bear",
    87: "hair drier", 88: "toothbrush",
    25: "giraffe",
    27: "backpack", 28: "handbag", 29: "tie", 30: "suitcase"
}
CLOTHING_IDS = [27, 28, 29, 31]  # Add more as needed, or detect "person" and assume their clothing

# === Run YOLOv8 and crop clothing
def crop_clothing(input_path, output_folder):
    os.makedirs(output_folder, exist_ok=True)
    model = YOLO(YOLO_MODEL_PATH)

    results = model(input_path)[0]
    image = cv2.imread(input_path)

    cropped_count = 0
    for i, box in enumerate(results.boxes):
        cls_id = int(box.cls.item())
        conf = float(box.conf.item())

        if conf < CONFIDENCE_THRESHOLD:
            continue

        class_name = model.names[cls_id]
        if cls_id in CLOTHING_IDS or "shirt" in class_name or "dress" in class_name or "jeans" in class_name or "jacket" in class_name:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            cropped = image[y1:y2, x1:x2]
            output_path = os.path.join(output_folder, f"cropped_{cropped_count}.jpg")
            cv2.imwrite(output_path, cropped)
            print(f"✅ Cropped clothing saved: {output_path}")
            cropped_count += 1

    if cropped_count == 0:
        print("❌ No clothing detected with confidence threshold.")

# === Run
if __name__ == "__main__":
    crop_clothing(INPUT_IMAGE, OUTPUT_CROP_DIR)
