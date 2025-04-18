"""
Formatting utilities.

This module provides functions for formatting sizes and parsing size specifications.
"""
import re
from typing import Union


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
