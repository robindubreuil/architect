"""
Formatting utilities.

This module provides functions for formatting sizes, parsing size specifications,
and consistent terminal output formatting.
"""
import re
from typing import Union, Optional


# ANSI Terminal Colors
class TermColors:
    """ANSI color codes for terminal output"""
    INFO = '\033[94m'     # Blue for informational messages
    SUCCESS = '\033[92m'  # Green for success messages 
    WARNING = '\033[93m'  # Yellow for warnings
    ERROR = '\033[91m'    # Red for errors
    SIM = '\033[96m'      # Cyan for simulation messages
    HEADER = '\033[95m'   # Purple for headers
    BOLD = '\033[1m'      # Bold text
    UNDERLINE = '\033[4m' # Underlined text
    ENDC = '\033[0m'      # End color


def colorize(message: str, color: str, enabled: bool = True) -> str:
    """
    Add color to a message if color output is enabled.
    
    Args:
        message: The message to colorize
        color: The color to use (from TermColors)
        enabled: Whether colorization is enabled
        
    Returns:
        Colorized message or original message if colors disabled
    """
    if not enabled:
        return message
    return f"{color}{message}{TermColors.ENDC}"


def bytes_to_human_readable(size_bytes: int) -> str:
    """
    Convert bytes to human readable format using binary units (KiB, MiB, GiB, TiB).
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Human readable size string with proper binary unit
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    
    for unit in ['KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB']:
        size_bytes /= 1024
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
    
    return f"{size_bytes:.2f} EiB"


def parse_size_spec(spec: str, disk_size_bytes: int) -> int:
    """
    Parse a size specification, which can be absolute or a percentage.
    
    Args:
        spec: Size specification (e.g., "100G", "100GB", "100GiB", "10%")
        disk_size_bytes: Total disk size in bytes
        
    Returns:
        Size in bytes
    """
    if spec.endswith("%"):
        percentage = float(spec.rstrip("%"))
        return int(disk_size_bytes * percentage / 100)
    
    # Parse size with unit
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([KMGT]i?B?)?$", spec, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid size specification: {spec}")
    
    value, unit = match.groups()
    value = float(value)
    
    if not unit or unit.upper() in ("B", ""):
        return int(value)
    
    # Binary units (powers of 1024)
    if unit.upper() in ("KIB", "K"):
        return int(value * 1024)
    if unit.upper() in ("MIB", "M"):
        return int(value * 1024**2)
    if unit.upper() in ("GIB", "G"):
        return int(value * 1024**3)
    if unit.upper() in ("TIB", "T"):
        return int(value * 1024**4)
    
    # Decimal units (powers of 1000)
    if unit.upper() in ("KB"):
        return int(value * 1000)
    if unit.upper() in ("MB"):
        return int(value * 1000**2)
    if unit.upper() in ("GB"):
        return int(value * 1000**3)
    if unit.upper() in ("TB"):
        return int(value * 1000**4)
    
    raise ValueError(f"Unknown unit: {unit}")