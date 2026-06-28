"""Image-cropping geometry and rendering shared by profile media pickers."""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps


@dataclass
class CropState:
    source_width: int
    source_height: int
    viewport_width: int
    viewport_height: int
    zoom: float = 1.0
    x: float = 0.0
    y: float = 0.0

    def __post_init__(self):
        if min(self.source_width, self.source_height, self.viewport_width, self.viewport_height) <= 0:
            raise ValueError("image and viewport dimensions must be positive")
        self.zoom = max(1.0, float(self.zoom))
        self.center()

    @property
    def base_scale(self) -> float:
        return max(
            self.viewport_width / self.source_width,
            self.viewport_height / self.source_height,
        )

    @property
    def scale(self) -> float:
        return self.base_scale * self.zoom

    @property
    def display_width(self) -> float:
        return self.source_width * self.scale

    @property
    def display_height(self) -> float:
        return self.source_height * self.scale

    def center(self) -> None:
        self.x = (self.viewport_width - self.display_width) / 2
        self.y = (self.viewport_height - self.display_height) / 2
        self.clamp()

    def clamp(self) -> None:
        self.x = min(0.0, max(self.viewport_width - self.display_width, self.x))
        self.y = min(0.0, max(self.viewport_height - self.display_height, self.y))

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.clamp()

    def set_zoom(self, zoom: float) -> None:
        old_width = self.display_width
        old_height = self.display_height
        center_x = (self.viewport_width / 2 - self.x) / old_width
        center_y = (self.viewport_height / 2 - self.y) / old_height
        self.zoom = min(4.0, max(1.0, float(zoom)))
        self.x = self.viewport_width / 2 - center_x * self.display_width
        self.y = self.viewport_height / 2 - center_y * self.display_height
        self.clamp()

    def source_box(self) -> tuple[float, float, float, float]:
        return (
            -self.x / self.scale,
            -self.y / self.scale,
            (self.viewport_width - self.x) / self.scale,
            (self.viewport_height - self.y) / self.scale,
        )


def image_size(path: str) -> tuple[int, int]:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image)
        return image.size


def render_crop(
    source_path: str,
    destination_path: str,
    state: CropState,
    output_size: tuple[int, int],
) -> str:
    """Render the visible viewport to a new image and return its path."""
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as source:
        source = ImageOps.exif_transpose(source)
        cropped = source.crop(state.source_box()).resize(output_size, Image.Resampling.LANCZOS)
        if destination.suffix.lower() in (".jpg", ".jpeg"):
            if cropped.mode not in ("RGB", "L"):
                background = Image.new("RGB", cropped.size, "white")
                if "A" in cropped.getbands():
                    background.paste(cropped, mask=cropped.getchannel("A"))
                else:
                    background.paste(cropped)
                cropped = background
            cropped.save(destination, quality=92, optimize=True)
        else:
            cropped.save(destination, optimize=True)
    return str(destination)
