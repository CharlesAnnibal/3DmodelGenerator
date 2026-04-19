"""Aggressively remove floor/shadow from creature images."""

from PIL import Image
from pathlib import Path

def remove_floor_aggressive(image_path, crop_percent=15):
    """
    Remove floor by cropping bottom X% of image.
    crop_percent: how much to remove from bottom (default 15%)
    """
    img = Image.open(image_path).convert("RGBA")
    width, height = img.size

    # Calculate crop amount
    remove_height = int(height * (crop_percent / 100))
    new_height = height - remove_height

    # Crop from top, removing bottom section
    cropped = img.crop((0, 0, width, new_height))

    return cropped


def process_folder(folder_path):
    """Remove floor from all PNG images in folder."""
    folder = Path(folder_path)

    for view in ["front", "side", "back"]:
        image_path = folder / f"{view}.png"
        if image_path.exists():
            print(f"Processing {view}.png...")
            result = remove_floor_aggressive(image_path, crop_percent=15)
            result.save(image_path)
            print(f"[OK] Saved: {image_path}")

if __name__ == "__main__":
    folder = r"C:\Users\charl\Projects\Games\modelGeneratorCLI\input\3-worcomb"
    process_folder(folder)
    print("\nDone! Floor removed from all images.")
