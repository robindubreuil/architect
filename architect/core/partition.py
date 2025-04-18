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


def get_architecture_specific_partition_type(args: Any) -> str:
    """
    Determine the appropriate partition type for Linux system partition
    based on architecture.
    
    Args:
        args: Command line arguments
        
    Returns:
        GPT partition type GUID
    """
    # If the partition is encrypted, use the LUKS type (architecture-independent)
    if args.hardware_encryption or args.software_encryption:
        return "CA7D7CCB-63ED-4C53-861C-1742536059CC"  # LUKS
        
    # Root partition type based on architecture
    arch_partition_types = {
        "x86_64": "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709",  # Linux root (x86-64)
        "arm64": "B921B045-1DF0-41C3-AF44-4C6F280D3FAE",   # Linux root (ARM64)
        "ia64": "993D8D3D-F80E-4225-855A-9DAF8ED7EA97",    # Linux root (IA-64)
        "arm": "69DAD710-2CE4-4E3C-B16C-21A1D49ABED3",     # Linux root (32-bit ARM)
        "x86": "44479540-F297-41B2-9AF7-D131D5F0458A"      # Linux root (32-bit x86)
    }
    
    # Use forced architecture if specified
    if hasattr(args, 'target_arch') and args.target_arch:
        arch = args.target_arch
    else:
        # Detect current architecture
        import platform
        arch = platform.machine().lower()
        
        # Normalize detected architecture
        if arch in ("x86_64", "amd64"):
            arch = "x86_64"
        elif arch in ("aarch64"):
            arch = "arm64"
        elif arch in ("i386", "i486", "i586", "i686"):
            arch = "x86"
        elif arch.startswith("arm"):
            if "64" in arch:
                arch = "arm64"
            else:
                arch = "arm"
    
    # Return appropriate type or default to generic Linux type if not recognized
    return arch_partition_types.get(arch, "0FC63DAF-8483-4772-8E79-3D69D8477DE4")


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
    script_lines.append("size=550MiB, type=U, attrs=RequiredPartition, name=\"EFI System\"")
    
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
        script_lines.append("size=16MiB, type=E3C9E316-0B5C-4DB8-817D-F92DF00215AE, name=\"Microsoft reserved\"")
        script_lines.append(f"size={args.windows}, type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7, name=\"Windows\"")
        script_lines.append(f"size={WINDOWS_RECOVERY_SIZE_MIB}MiB, type=DE94BBA4-06D1-4D40-A16A-BFD50179D6AC, attrs=RequiredPartition,63, name=\"Windows Recovery\"")
            
        system_partition_type = get_architecture_specific_partition_type(args)

        # Get architecture-specific partition type
        system_partition_type = get_architecture_specific_partition_type(args)

        # Add Linux partitions
        script_lines.append("# Linux partitions")
        script_lines.append("size=1GiB, type=L, name=\"Linux boot\"")
        script_lines.append(f"size=+, type={system_partition_type}, name=\"Linux root\"")
    
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