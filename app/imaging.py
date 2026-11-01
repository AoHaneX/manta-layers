"""Pixel helpers shared by several tools, computed with Pillow only (no Qt).

Transparent margins are found from the alpha channel; crops never resample, so
pixel art keeps its exact pixels.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from PIL import Image


def alpha_bounds(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Box (left, top, right, bottom) of the pixels that are not fully transparent."""
    return (image if image.mode == "RGBA" else image.convert("RGBA")).getchannel("A").getbbox()


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


def grid_shape(size: tuple[int, int], grid: SpriteGrid) -> tuple[int, int]:
    """Columns and rows of the grid whose cells lie entirely inside an image of ``size``.

    Explicit counts are clamped to what fits: an oversized value (a typo, or an
    intermediate value while typing) never makes callers walk cells outside the image.
    """
    grid.validate()
    width, height = size
    fit_columns = _count(width - grid.offset_x, grid.cell_width, grid.spacing_x)
    fit_rows = _count(height - grid.offset_y, grid.cell_height, grid.spacing_y)
    return min(grid.columns or fit_columns, fit_columns), min(grid.rows or fit_rows, fit_rows)


def grid_cells(size: tuple[int, int], grid: SpriteGrid) -> list[tuple[int, int, tuple[int, int, int, int]]]:
    """Cells (row, column, box) entirely inside an image of ``size``.

    Cells that would extend past the image are left out rather than padded,
    so every extracted sprite contains only real pixels.
    """
    columns, rows = grid_shape(size, grid)
    cells = []
    for row in range(rows):
        top = grid.offset_y + row * (grid.cell_height + grid.spacing_y)
        for column in range(columns):
            left = grid.offset_x + column * (grid.cell_width + grid.spacing_x)
            cells.append((row, column, (left, top, left + grid.cell_width, top + grid.cell_height)))
    return cells


def iter_cells(image: Image.Image, grid: SpriteGrid) -> Iterator[
        tuple[int, int, tuple[int, int, int, int], Image.Image, tuple[int, int, int, int] | None]]:
    """Cells of a sheet one at a time: (row, column, box, RGBA cell, visible bounds or None if empty).

    The single implementation of the cutting, shared by ``extract_sprites`` and the
    slicer preview; being lazy, it never holds every cell in memory at once.
    """
    sheet = image if image.mode == "RGBA" else image.convert("RGBA")
    for row, column, box in grid_cells(sheet.size, grid):
        cell = sheet.crop(box)
        yield row, column, box, cell, alpha_bounds(cell)


def extract_sprites(image: Image.Image, grid: SpriteGrid, trim: bool = False,
                    skip_empty: bool = True) -> list[tuple[int, int, Image.Image]]:
    """Sprites (row, column, image) cut from a sheet, optionally trimmed of transparent margins."""
    return [(row, column, cell.crop(bounds) if trim and bounds is not None else cell)
            for row, column, _box, cell, bounds in iter_cells(image, grid)
            if bounds is not None or not skip_empty]
