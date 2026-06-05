"""
Base caption style class - all caption styles inherit from this
"""
from abc import ABC, abstractmethod
from typing import Tuple, List
import pysubs2


class BaseCaptionStyle(ABC):
    """Abstract base class for all caption styling engines"""

    def __init__(self):
        self.name = "base"
        self.font_name = "Arial"
        self.font_size = 85
        self.alignment = 5  # Center-center
        self.outline = 3.0
        self.primary_color = pysubs2.Color(255, 255, 255)
        self.secondary_color = pysubs2.Color(255, 255, 0)
        self.back_color = pysubs2.Color(0, 0, 0, 180)
        self.margin_l = 0
        self.margin_r = 0
        self.margin_v = 100

    @abstractmethod
    def style_subtitle(self, text: str, duration_ms: int) -> str:
        """
        Apply styling to a subtitle text

        Args:
            text: Raw subtitle text
            duration_ms: Duration of subtitle in milliseconds

        Returns:
            Styled text with ASS/SSA formatting tags
        """
        pass

    def create_style(self) -> pysubs2.SSAStyle:
        """Create a pysubs2 style object"""
        return pysubs2.SSAStyle(
            fontname=self.font_name,
            fontsize=self.font_size,
            primarycolor=self.primary_color,
            secondarycolor=self.secondary_color,
            backcolor=self.back_color,
            bold=True,
            alignment=self.alignment,
            outline=self.outline,
            marginv=self.margin_v,
            marginl=self.margin_l,
            marginr=self.margin_r
        )

    def get_margin_settings(self) -> dict:
        """Get margin settings for FFmpeg subtitles filter"""
        return {
            "margin_l": self.margin_l,
            "margin_r": self.margin_r,
            "margin_v": self.margin_v
        }