"""
Disk partitioning module.

This module handles disk partitioning operations using sfdisk for simpler and more
efficient partition layout creation.
"""
import os
import logging
import subprocess
import time
from typing import Dict, Any, List

from architect.utils.command import CommandRunner
from architect.utils.format import TermColors, colorize, parse_size_spec
from architect.utils.types import DiskInfo, PartitionTable
from architect.core.exceptions import NotEnoughSpaceError, PartitioningError

logger = logging.getLogger('architect')

# Constants
DEFAULT_SSD_OVERPROVISION = 5  # 5% for SSDs
MIN_WINDOWS_SIZE_GIB = 21      # Minimum Windows partition size in GiB
WINDOWS_RECOVERY_SIZE_MIB = 750  # Size for Windows Recovery partition


def get_partition_device_name(disk: str, partition_number: int) -> str:
    """
    Generate the appropriate partition device name based on disk type.
    
    Args:
        disk: Path to the disk device
        partition_number: Partition number
        
    Returns:
        Partition device path
    """
    # Check if this is an NVMe disk
    if "nvme" in disk.lower():
        return f"{disk}p{partition_number}"
    # Otherwise, assume standard disk naming convention
    else:
        return f"{disk}{partition_number}"


def prepare_disk(disk: str, disk_info: DiskInfo, args: Any, cmd_runner: CommandRunner) -> PartitionTable:
    """
    Prepare the disk by wiping and partitioning using sfdisk.
    
    Args:
        disk: Path to the disk device
        disk_info: Dict containing disk info
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Dict mapping partition roles to device paths
        
    Raises:
        PartitioningError: If there's an error in partitioning
        NotEnoughSpaceError: If not enough space for Windows partition
    """
    logger.info(colorize(f"Preparing disk {disk}", TermColors.INFO, cmd_runner.colored_output))
    
    # Wipe the disk
    logger.info("Wiping disk")
    try:
        cmd_runner.run(["wipefs", "-a", disk])
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to wipe disk: {e}")
    
    # Create the partition table using sfdisk
    logger.info("Creating GPT partition table using sfdisk")
    
    # Build sfdisk script
    script_lines = ["label: gpt"]
    
    # Add metadata comments
    if args.overprovision:
        script_lines.append(f"# Overprovisioning: {args.overprovision}")
    if args.windows:
        script_lines.append("# Dual-boot configuration with Windows")
    
    # Always add the EFI partition (shared between Windows and Linux)
    script_lines.append("size=550MiB, type=U, name=\"EFI System\"")
    
    # Add Windows partitions if requested
    if args.windows:
        # Validate Windows size - if it's not valid, let it raise an exception
        try:
            # Check if minimum size is met
            windows_bytes = parse_size_spec(args.windows, disk_info["size_bytes"])
            windows_gib = windows_bytes / (1024**3)
            
            if windows_gib < MIN_WINDOWS_SIZE_GIB:
                raise NotEnoughSpaceError(
                    f"Windows partition size must be at least {MIN_WINDOWS_SIZE_GIB} GiB, got {windows_gib:.1f} GiB"
                )
        except ValueError:
            raise PartitioningError(f"Invalid Windows size specification: {args.windows}")
        
        # Windows partitions group
        script_lines.append("# Windows partitions")
        script_lines.append("size=16MiB, type=0x0c01, name=\"Microsoft reserved\"")
        script_lines.append(f"size={args.windows}, type=0x0700, name=\"Windows\"")
        script_lines.append(f"size={WINDOWS_RECOVERY_SIZE_MIB}MiB, type=0x2700, name=\"Windows Recovery\"")
    
    # Add Linux partitions
    script_lines.append("# Linux partitions")
    script_lines.append("size=1GiB, type=L, name=\"Boot\"")
    script_lines.append("size=+, type=L, name=\"Linux System\"")
    
    # Join the script lines
    script = "\n".join(script_lines)
    
    # Log the script
    logger.info("Applying partition table:")
    for line in script_lines:
        logger.info(f"  {line}")
    
    # Apply the partitioning
    try:
        cmd_runner.run(["sfdisk", disk], input=script)
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to create partition table: {e}")
    
    # Allow kernel to process the new partition table
    try:
        cmd_runner.run(["udevadm", "settle"])
    except subprocess.CalledProcessError as e:
        logger.warning(colorize(f"udevadm settle failed, but continuing: {e}", 
                               TermColors.WARNING, cmd_runner.colored_output))
        # Sleep a bit to give the kernel time to recognize partitions
        time.sleep(2)
    
    # Map partition roles to device paths
    partitions: PartitionTable = {}
    
    if args.windows:
        partitions["efi"] = get_partition_device_name(disk, 1)
        partitions["msr"] = get_partition_device_name(disk, 2)
        partitions["windows"] = get_partition_device_name(disk, 3)
        partitions["recovery"] = get_partition_device_name(disk, 4)
        partitions["boot"] = get_partition_device_name(disk, 5)
        partitions["system"] = get_partition_device_name(disk, 6)
    else:
        partitions["efi"] = get_partition_device_name(disk, 1)
        partitions["boot"] = get_partition_device_name(disk, 2)
        partitions["system"] = get_partition_device_name(disk, 3)
    
    logger.info(colorize("Partitioning completed successfully", 
                        TermColors.SUCCESS, cmd_runner.colored_output))
    return partitions