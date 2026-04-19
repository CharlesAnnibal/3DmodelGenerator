"""Split a horizontally-arranged 3-view creature image into separate transparent PNGs."""

from PIL import Image
import numpy as np
import cv2
from pathlib import Path

def remove_text_from_section(image_array):
    """
    Remove text elements from image using contour detection.
    Keeps only the largest object (the creature) and removes small objects (text).
    """
    # Convert RGBA to BGR for OpenCV
    if len(image_array.shape) == 3 and image_array.shape[2] == 4:
        bgr = cv2.cvtColor(image_array, cv2.COLOR_RGBA2BGR)
    else:
        bgr = image_array[:, :, :3]

    # Convert to grayscale
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    # Threshold to get binary image (creature and text are dark, background is light)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return image_array

    # Sort contours by area, keep only the largest (the creature)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    largest_contour = contours[0]

    # Create a mask with only the largest contour
    mask = np.zeros(binary.shape, dtype=np.uint8)
    cv2.drawContours(mask, [largest_contour], 0, 255, -1)

    # Apply mask to the original image
    result = image_array.copy()
    if len(result.shape) == 3 and result.shape[2] == 4:
        # Set alpha channel to 0 where mask is 0
        result[:, :, 3] = mask

    return result


def split_creature_image(image_path, output_dir=None):
    """
    Split a 3-view creature image into front, side, and back.
    Removes text and white/light background, saves as transparent PNGs.
    """
    image_path = Path(image_path)

    if output_dir is None:
        output_dir = image_path.parent
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load image
    img = Image.open(image_path).convert("RGBA")
    width, height = img.size

    # Split into 3 equal parts
    section_width = width // 3
    sections = {
        "front": img.crop((0, 0, section_width, height)),
        "side": img.crop((section_width, 0, 2 * section_width, height)),
        "back": img.crop((2 * section_width, 0, width, height)),
    }

    # Remove text and white/light background
    for view_name, section in sections.items():
        # Convert to RGBA if needed
        section = section.convert("RGBA")
        data = np.array(section)

        # Remove text using contour detection
        data = remove_text_from_section(data)

        # Find white or near-white pixels (high R, G, B values)
        threshold = 220
        white_mask = (data[:, :, 0] > threshold) & \
                     (data[:, :, 1] > threshold) & \
                     (data[:, :, 2] > threshold)

        # Set white pixels to transparent
        data[white_mask, 3] = 0

        # Convert back to image
        result = Image.fromarray(data)

        # Save
        output_path = output_dir / f"{view_name}.png"
        result.save(output_path)
        print(f"[OK] Saved: {output_path}")

if __name__ == "__main__":
    image_path = r"C:\Users\charl\Projects\Games\modelGeneratorCLI\input\3-worcomb\20260407_1026_Image Generation_remix_01knkm75kpegftsfq1qbd33qh2.png"

    # Split and save to the same folder as input
    split_creature_image(image_path)
    print("\nDone! Images saved to input/3-worcomb/")
