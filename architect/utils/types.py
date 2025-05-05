"""
Type definitions for architect.

This module provides TypedDict definitions and other type aliases
for better type checking throughout the codebase.
"""
from typing import Dict, List, Optional, TypedDict, Union, Literal


class DiskInfo(TypedDict):
    """Information about a disk device"""
    size_bytes: int
    size_gib: float
    rotational: bool
    nvme: bool
    model: str
    trim_supported: bool
    cpu_count: int


class PartitionInfo(TypedDict):
    """Information about a single partition"""
    device: str
    role: str
    filesystem: Optional[str]
    size_bytes: Optional[int]


# Mapping of partition roles to device paths
PartitionTable = Dict[str, str]

# Mapping of mount points to mount options
MountOptions = Dict[str, str]

# Types of encryption
EncryptionType = Literal["none", "hardware", "software", "hardware_and_software"]