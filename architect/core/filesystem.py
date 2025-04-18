"""
Filesystem creation and management module.

This module handles filesystem creation and btrfs subvolume setup.
"""
import os
import logging
import subprocess
import tempfile
from typing import Dict, Any
from pathlib import Path

from architect.utils.command import CommandRunner, SimulationMode
from architect.core.exceptions import FilesystemError

logger = logging.getLogger('architect')


def create_filesystems(partitions: Dict[str, str], disk_info: Dict[str, Any], args: Any, cmd_runner: CommandRunner) -> None:
    """
    Create filesystems on partitions.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        disk_info: Dict containing disk info
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        FilesystemError: If there's an error in filesystem creation
    """
    logger.info("Creating filesystems")
    
    # Create FAT32 on EFI partition
    try:
        cmd_runner.run(["mkfs.fat", "-F32", "-n", "ESP", partitions["efi"]])
        logger.info(f"Created FAT32 filesystem on {partitions['efi']}")
    except subprocess.CalledProcessError as e:
        raise FilesystemError(f"Failed to create FAT32 filesystem: {e}")
    
    # Create ext4 on boot partition
    try:
        cmd_runner.run(["mkfs.ext4", "-L", "boot", partitions["boot"]])
        logger.info(f"Created ext4 filesystem on {partitions['boot']}")
    except subprocess.CalledProcessError as e:
        raise FilesystemError(f"Failed to create ext4 filesystem: {e}")
    
    # Create btrfs on system partition
    try:
        cmd_runner.run(["mkfs.btrfs", "-L", "rootfs", partitions["system"]])
        logger.info(f"Created btrfs filesystem on {partitions['system']}")
    except subprocess.CalledProcessError as e:
        raise FilesystemError(f"Failed to create btrfs filesystem: {e}")


def create_btrfs_subvolumes(partitions: Dict[str, str], args: Any, cmd_runner: CommandRunner) -> Dict[str, str]:
    """
    Create btrfs subvolumes.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Dict mapping subvolume names to their paths
        
    Raises:
        FilesystemError: If there's an error in subvolume creation
    """
    logger.info("Creating btrfs subvolumes")
    
    system_partition = partitions["system"]
    
    # Create a temporary mount point
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        temp_dir = "/tmp/architect-sim-mount"  # Simulated path
    else:
        temp_dir = tempfile.mkdtemp()
    
    try:
        # Mount the btrfs partition
        cmd_runner.run(["mount", system_partition, temp_dir])
        
        # Define subvolumes to create
        subvolumes = [
            "@",           # Root
            "@boot",       # Boot files
            "@home",       # User home directories
            "@opt",        # Optional software
            "@root",       # Root user home
            "@srv",        # Service data
            "@tmp",        # Temporary files
            "@usr",        # System binaries and libraries
            "@var",        # Variable data
            "@var_log",    # System logs
            "@var_tmp"     # Persistent temporary files
        ]
        
        subvolume_paths = {}
        
        # Create each subvolume
        for subvol in subvolumes:
            subvol_path = os.path.join(temp_dir, subvol)
            try:
                cmd_runner.run(["btrfs", "subvolume", "create", subvol_path])
                subvolume_paths[subvol] = subvol_path
                logger.info(f"Created subvolume {subvol}")
            except subprocess.CalledProcessError as e:
                raise FilesystemError(f"Failed to create subvolume {subvol}: {e}")
        
        # Clean up
        cmd_runner.run(["umount", temp_dir])
        
        if cmd_runner.simulation_mode != SimulationMode.SIMULATE:
            os.rmdir(temp_dir)
        
        return subvolume_paths
    
    except Exception as e:
        # Clean up in case of error
        try:
            cmd_runner.run(["umount", temp_dir], check=False)
            if cmd_runner.simulation_mode != SimulationMode.SIMULATE:
                os.rmdir(temp_dir)
        except Exception:
            pass
        raise FilesystemError(f"Error creating btrfs subvolumes: {e}")
