"""
Disk partitioning module.

This module handles disk partitioning operations, including partition creation,
sizing, and layout.
"""
import os
import logging
import subprocess
import time
from typing import Dict, Any

from architect.utils.command import CommandRunner
from architect.utils.format import parse_size_spec
from architect.core.exceptions import NotEnoughSpaceError, PartitioningError

logger = logging.getLogger('architect')

# Constants
DEFAULT_SSD_OVERPROVISION = 5  # 5% for SSDs
MIN_WINDOWS_SIZE_GIB = 21      # Minimum Windows partition size in GiB
RECOMMENDED_WINDOWS_SIZE_GIB = 64  # Recommended Windows partition size in GiB

# Partition sizes in MiB (binary units)
EFI_PARTITION_SIZE_MIB = 550
BOOT_PARTITION_SIZE_MIB = 1024
MSR_PARTITION_SIZE_MIB = 16
WINDOWS_RECOVERY_SIZE_MIB = 750


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


def prepare_disk(disk: str, disk_info: Dict[str, Any], args: Any, cmd_runner: CommandRunner) -> Dict[str, str]:
    """
    Prepare the disk by wiping and partitioning.
    
    Args:
        disk: Path to the disk device
        disk_info: Dict containing disk info
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Dict mapping partition roles to device paths
        
    Raises:
        PartitioningError: If there's an error in partitioning
    """
    logger.info(f"Preparing disk {disk}")
    
    # Calculate sizes
    disk_size_bytes = disk_info["size_bytes"]
    
    # Calculate overprovisioning size
    overprovision_bytes = 0
    if args.overprovision:
        overprovision_bytes = parse_size_spec(args.overprovision, disk_size_bytes)
    elif disk_info["rotational"] is False:  # Default 5% for SSDs if not specified
        overprovision_bytes = int(disk_size_bytes * DEFAULT_SSD_OVERPROVISION / 100)
    
    # Calculate Windows partition size if requested
    windows_bytes = 0
    if args.windows:
        windows_bytes = parse_size_spec(args.windows, disk_size_bytes)
        windows_gib = windows_bytes / (1024**3)  # Convert to binary GiB
        
        if windows_gib < MIN_WINDOWS_SIZE_GIB:
            raise NotEnoughSpaceError(f"Windows partition size must be at least {MIN_WINDOWS_SIZE_GIB} GiB")
        
        if windows_gib < RECOMMENDED_WINDOWS_SIZE_GIB:
            logger.warning(f"Windows partition size {windows_gib:.1f} GiB is less than recommended {RECOMMENDED_WINDOWS_SIZE_GIB} GiB")
    
    # Calculate sizes for EFI and boot partitions (binary units)
    efi_size_mib = EFI_PARTITION_SIZE_MIB
    boot_size_mib = BOOT_PARTITION_SIZE_MIB
    logger.info(f"EFI partition size: {efi_size_mib} MiB")
    logger.info(f"Boot partition size: {boot_size_mib} MiB")
    
    # Calculate partition sizes in bytes for easier comparison
    efi_bytes = efi_size_mib * 1024 * 1024    # MiB to bytes
    boot_bytes = boot_size_mib * 1024 * 1024  # MiB to bytes
    
    # Calculate Windows MSR and recovery partition sizes if needed
    msr_bytes = 0
    recovery_bytes = 0
    if args.windows:
        msr_bytes = MSR_PARTITION_SIZE_MIB * 1024**2
        recovery_bytes = WINDOWS_RECOVERY_SIZE_MIB * 1024**2
    
    # Calculate remaining space for system partition
    system_bytes = disk_size_bytes - efi_bytes - boot_bytes - overprovision_bytes - windows_bytes - msr_bytes - recovery_bytes
    
    # Require at least 5 GiB for system
    if system_bytes < 5 * 1024**3:
        raise NotEnoughSpaceError("Not enough space for system partition (minimum 5 GiB required)")
    
    # Wipe the disk
    logger.info("Wiping disk")
    try:
        cmd_runner.run(["wipefs", "-a", disk])
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to wipe disk: {e}")
    
    # Create a new partition table
    logger.info("Creating GPT partition table")
    try:
        cmd_runner.run(["parted", "-s", disk, "mklabel", "gpt"])
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to create partition table: {e}")
    
    # Create partitions
    partitions = {}
    
    # EFI partition
    start = 1  # Start at 1 MiB for alignment
    end = start + (efi_bytes // 1024**2)
    logger.info(f"Creating EFI partition ({EFI_PARTITION_SIZE_MIB} MiB)")
    try:
        cmd_runner.run([
            "parted", "-s", disk,
            "mkpart", "EFI", "fat32", f"{start}MiB", f"{end}MiB",
            "set", "1", "esp", "on"
        ])
        partitions["efi"] = get_partition_device_name(disk, 1)
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to create EFI partition: {e}")
    
    # Boot partition
    start = end
    end = start + (boot_bytes // 1024**2)
    logger.info(f"Creating boot partition ({BOOT_PARTITION_SIZE_MIB} MiB)")
    try:
        cmd_runner.run([
            "parted", "-s", disk,
            "mkpart", "boot", "ext4", f"{start}MiB", f"{end}MiB"
        ])
        partitions["boot"] = get_partition_device_name(disk, 2)
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to create boot partition: {e}")
    
    # System partition
    start = end
    end = start + (system_bytes // 1024**2)
    logger.info(f"Creating system partition ({system_bytes // (1024**3)} GiB)")
    try:
        cmd_runner.run([
            "parted", "-s", disk,
            "mkpart", "system", "btrfs", f"{start}MiB", f"{end}MiB"
        ])
        partitions["system"] = get_partition_device_name(disk, 3)
    except subprocess.CalledProcessError as e:
        raise PartitioningError(f"Failed to create system partition: {e}")
    
    # Windows partitions if requested
    if args.windows:
        # Microsoft Reserved Partition (MSR)
        start = end
        end = start + MSR_PARTITION_SIZE_MIB
        logger.info(f"Creating Microsoft Reserved Partition ({MSR_PARTITION_SIZE_MIB} MiB)")
        try:
            cmd_runner.run([
                "parted", "-s", disk,
                "mkpart", "msrreserved", "ntfs", f"{start}MiB", f"{end}MiB",
                "set", "4", "msftres", "on"
            ])
            partitions["msr"] = get_partition_device_name(disk, 4)
        except subprocess.CalledProcessError as e:
            raise PartitioningError(f"Failed to create MSR partition: {e}")
        
        # Windows partition
        start = end
        windows_main_bytes = windows_bytes - msr_bytes - recovery_bytes
        end = start + (windows_main_bytes // 1024**2)
        logger.info(f"Creating Windows partition ({windows_main_bytes // (1024**3)} GiB)")
        try:
            cmd_runner.run([
                "parted", "-s", disk,
                "mkpart", "windows", "ntfs", f"{start}MiB", f"{end}MiB"
            ])
            partitions["windows"] = get_partition_device_name(disk, 5)
        except subprocess.CalledProcessError as e:
            raise PartitioningError(f"Failed to create Windows partition: {e}")
        
        # Windows recovery partition
        start = end
        end = start + WINDOWS_RECOVERY_SIZE_MIB
        logger.info(f"Creating Windows recovery partition ({WINDOWS_RECOVERY_SIZE_MIB} MiB)")
        try:
            cmd_runner.run([
                "parted", "-s", disk,
                "mkpart", "recovery", "ntfs", f"{start}MiB", f"{end}MiB",
                "set", "6", "msftdata", "on"
            ])
            partitions["recovery"] = get_partition_device_name(disk, 6)
        except subprocess.CalledProcessError as e:
            raise PartitioningError(f"Failed to create recovery partition: {e}")
    
    # Give the kernel a chance to update device nodes
    try:
        cmd_runner.run(["udevadm", "settle"])
    except subprocess.CalledProcessError as e:
        logger.warning(f"udevadm settle failed, but continuing: {e}")
    
    logger.info("Partitioning completed successfully")
    return partitions
