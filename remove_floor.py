"""Remove floor/ground shadow from creature images."""

from PIL import Image
import numpy as np
import cv2
from pathlib import Path

def remove_floor_from_image(image_path):
    """
    Remove the floor/shadow from bottom of creature image.
    Uses contour detection to find the creature and removes everything below it.
    """
    img = Image.open(image_path).convert("RGBA")
    data = np.array(img)

    # Get BGR for OpenCV
    bgr = cv2.cvtColor(data[:, :, :3], cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Create binary mask: dark pixels (creature) vs light (background)
    # Threshold to find creature (dark parts) vs floor/background
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return img

    # Find the largest contour (the creature)
    largest = max(contours, key=cv2.contourArea)

    # Get bounding box of creature
    x, y, w, h = cv2.boundingRect(largest)

    # Get bottom of creature with small margin
    creature_bottom = y + h + 20

    # Crop image to remove floor
    cropped = img.crop((0, 0, img.width, creature_bottom))

    # Pad to reasonable height
    new_height = int(img.height * 0.9)
    if cropped.height < new_height:
        result = Image.new("RGBA", (img.width, new_height), (0, 0, 0, 0))
        result.paste(cropped, (0, 0), cropped)
    else:
        result = cropped

    return result


def process_folder(folder_path):
    """Remove floor from all PNG images in folder."""
    folder = Path(folder_path)

    for view in ["front", "side", "back"]:
        image_path = folder / f"{view}.png"
        if image_path.exists():
            print(f"Processing {view}.png...")
            result = remove_floor_from_image(image_path)
            result.save(image_path)
            print(f"[OK] Saved: {image_path}")

if __name__ == "__main__":
    folder = r"C:\Users\charl\Projects\Games\modelGeneratorCLI\input\3-worcomb"
    process_folder(folder)
    print("\nDone! Floor removed from all images.")
