"""Bounded deterministic renderers for perception debugging."""

from __future__ import annotations

from html import escape

from arc3.perception.components import Component
from arc3.perception.delta import FrameDelta
from arc3.perception.frame import NormalizedGrid

_GLYPHS = "0123456789ABCDEF"
_DEFAULT_PALETTE = (
    "#000000",
    "#0074D9",
    "#FF4136",
    "#2ECC40",
    "#FFDC00",
    "#AAAAAA",
    "#F012BE",
    "#FF851B",
    "#7FDBFF",
    "#870C25",
    "#B10DC9",
    "#3D9970",
    "#85144B",
    "#01FF70",
    "#FFB6C1",
    "#FFFFFF",
)


def render_grid_text(grid: NormalizedGrid, *, spaced: bool = False) -> str:
    """Render all cells as bounded single-character palette indices."""

    separator = " " if spaced else ""
    return "\n".join(separator.join(_GLYPHS[cell] for cell in row) for row in grid.cells)


def render_grid_svg(
    grid: NormalizedGrid,
    *,
    cell_size: int = 12,
    palette: tuple[str, ...] = _DEFAULT_PALETTE,
) -> str:
    """Render deterministic standalone SVG with validated numeric geometry."""

    if not 1 <= cell_size <= 64:
        raise ValueError("cell_size must be within 1..64")
    if len(palette) != 16:
        raise ValueError("palette must contain exactly 16 colors")
    colors = tuple(escape(color, quote=True) for color in palette)
    width = grid.width * cell_size
    height = grid.height * cell_size
    rects = "".join(
        f'<rect x="{x * cell_size}" y="{y * cell_size}" width="{cell_size}" '
        f'height="{cell_size}" fill="{colors[cell]}"/>'
        for y, row in enumerate(grid.cells)
        for x, cell in enumerate(row)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges">{rects}</svg>'
    )


def summarize_perception(
    grid: NormalizedGrid,
    *,
    components: tuple[Component, ...] = (),
    delta: FrameDelta | None = None,
    maximum_component_details: int = 8,
) -> str:
    """Return a concise measurement summary with bounded component detail."""

    if maximum_component_details < 0:
        raise ValueError("maximum_component_details must be non-negative")
    lines = [
        f"grid={grid.width}x{grid.height} hash={grid.digest} palette={list(grid.palette)}",
        f"components={len(components)}",
    ]
    for component in components[:maximum_component_details]:
        lines.append(
            "component="
            f"{component.component_id[:16]} color={component.color} area={component.area} "
            f"bounds=({component.bounds.left},{component.bounds.top})-"
            f"({component.bounds.right},{component.bounds.bottom})"
        )
    omitted = len(components) - maximum_component_details
    if omitted > 0:
        lines.append(f"components_omitted={omitted}")
    if delta is not None:
        lines.append(
            f"changed_cells={delta.changed_cell_count} "
            f"metadata_changes={len(delta.metadata_changes)} noop={str(delta.apparent_noop).lower()}"
        )
    return "\n".join(lines)
