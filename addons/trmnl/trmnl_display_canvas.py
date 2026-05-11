"""Shared TRMNL e-ink canvas dimensions and content vs footer layout.

Layout renderers (list, calendar month/week) produce an image of size
``(DISPLAY_WIDTH, CONTENT_HEIGHT)``. The profile composites that onto a full
``800×480`` frame and draws the poll footer in the reserved bottom band.
"""
from __future__ import annotations

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Bottom band: 1 px separator + text area (~25 px). Total 20–28 px as requested.
FOOTER_BAND_HEIGHT = 26
CONTENT_HEIGHT = DISPLAY_HEIGHT - FOOTER_BAND_HEIGHT

# Y coordinate of the horizontal separator (last content row is y < SEPARATOR_Y).
SEPARATOR_Y = CONTENT_HEIGHT
FOOTER_BODY_TOP = SEPARATOR_Y + 1
