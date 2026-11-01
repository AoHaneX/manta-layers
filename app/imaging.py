"""Pixel helpers shared by several tools, computed with Pillow only (no Qt).

Transparent margins are found from the alpha channel; crops never resample, so
pixel art keeps its exact pixels.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


def alpha_bounds(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Box (left, top, right, bottom) of the pixels that are not fully transparent."""
    return image.convert("RGBA").getchannel("A").getbbox()


def trim_transparent(image: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]] | None:
    """Image cropped to its visible pixels with the crop box; None if fully transparent."""
    box = alpha_bounds(image)
    if box is None:
        return None
    return image.crop(box), box


# --- Spritesheets ---------------------------------------------------------------------


@dataclass(frozen=True)
class SpriteGrid:
    """Regular grid of cells laid over a spritesheet (all values in pixels).

    ``columns`` and ``rows`` at 0 mean "as many as fit in the image".
    """

    cell_width: int
    cell_height: int
    columns: int = 0
    rows: int = 0
    spacing_x: int = 0
    spacing_y: int = 0
    offset_x: int = 0
    offset_y: int = 0

    def validate(self) -> None:
        if self.cell_width < 1 or self.cell_height < 1:
            raise ValueError("La taille des cellules doit être d'au moins 1 px")
        if min(self.columns, self.rows, self.spacing_x, self.spacing_y, self.offset_x, self.offset_y) < 0:
            raise ValueError("Les valeurs de la grille ne peuvent pas être négatives")


def _count(available: int, cell: int, spacing: int) -> int:
    return max(0, (available + spacing) // (cell + spacing)) if available >= cell else 0


def grid_cells(size: tuple[int, int], grid: SpriteGrid) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    """Cells (row, column, box) entirely inside an image of ``size``.

    Cells that would extend past the image are left out rather than padded,
    so every extracted sprite contains only real pixels.
    """
    grid.validate()
    width, height = size
    columns = grid.columns or _count(width - grid.offset_x, grid.cell_width, grid.spacing_x)
    rows = grid.rows or _count(height - grid.offset_y, grid.cell_height, grid.spacing_y)
    cells = []
    for row in range(rows):
        top = grid.offset_y + row * (grid.cell_height + grid.spacing_y)
        for column in range(columns):
            left = grid.offset_x + column * (grid.cell_width + grid.spacing_x)
            box = (left, top, left + grid.cell_width, top + grid.cell_height)
            if box[2] <= width and box[3] <= height:
                cells.append((row, column, box))
    return cells


def extract_sprites(image: Image.Image, grid: SpriteGrid, trim: bool = False,
                    skip_empty: bool = True) -> list[tuple[int, int, Image.Image]]:
    """Sprites (row, column, image) cut from a sheet, optionally trimmed of transparent margins."""
    sheet = image.convert("RGBA")
    sprites = []
    for row, column, box in grid_cells(sheet.size, grid):
        cell = sheet.crop(box)
        bounds = alpha_bounds(cell)
        if bounds is None:
            if skip_empty:
                continue
        elif trim:
            cell = cell.crop(bounds)
        sprites.append((row, column, cell))
    return sprites
