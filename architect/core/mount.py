"""
Filesystem mounting module.

This module handles mounting filesystems and setting mount options.
Refactored for better code organization and readability.
"""
import os
import logging
import subprocess
from typing import Dict, Any, List
from pathlib import Path

from architect.utils.command import CommandRunner, SimulationMode
from architect.utils.format import TermColors, colorize
from architect.utils.types import DiskInfo, MountOptions, PartitionTable
from architect.core.exceptions import MountError

logger = logging.getLogger('architect')


def determine_mount_options(disk_info: DiskInfo, args: Any) -> MountOptions:
    """
    Determine mount options for each filesystem.
    
    Args:
        disk_info: Dict containing disk info
        args: Command line arguments
        
    Returns:
        Dict mapping mount points to their mount options
    """
    # Base mount options with security defaults following ANSSI recommendations
    # We apply reasonable security options by default, even without hardened mode
    mount_options: MountOptions = {
        "/": "defaults,noatime",
        "/boot": "defaults,nodev,nosuid",
        "/boot/efi": "umask=0077,nodev,nosuid,noexec",
        "/home": "defaults,nodev,nosuid",
        "/opt": "defaults,nodev,nosuid",
        "/root": "defaults,nodev,nosuid",
        "/srv": "defaults,nodev,nosuid",
        "/tmp": "defaults,nodev,nosuid,noexec",
        "/usr": "defaults,nodev",
        "/var": "defaults,nosuid,nodev",
        "/var/log": "defaults,nodev,nosuid,noexec",
        "/var/tmp": "defaults,nodev,nosuid,noexec"
    }
    
    # Apply even more restrictive hardened mount options if requested
    if args.hardened:
        logger.info(colorize("Applying hardened mount options according to ANSSI recommendations", 
                            TermColors.INFO, args.no_color))
        mount_options.update({
            # In hardened mode, we further restrict some partitions
            "/boot": "defaults,nodev,nosuid,noauto",
            "/var": "defaults,nosuid,nodev,noexec", # Note: This may cause issues with package managers
            # Add hidepid=2 to /proc in fstab separately
        })
        logger.warning(colorize("Note: Hardened mode with noexec on /var may require special handling for package management", 
                               TermColors.WARNING, not args.no_color))
    
    # Add discard option for SSD partitions if TRIM is supported
    if not disk_info["rotational"] and disk_info.get("trim_supported", False):
        logger.info(colorize("Adding discard mount option for SSD partitions (TRIM supported)", 
                            TermColors.INFO, not args.no_color))
        for mountpoint in ["/boot", "/boot/efi"]:
            mount_options[mountpoint] += ",discard"
    
    # Determine filesystem-wide mount options for btrfs
    fs_options = ""
    
    # Use provided options if specified
    if args.btrfs_options:
        fs_options = args.btrfs_options
    else:
        # Apply default options based on disk type
        if disk_info["rotational"]:
            # HDD defaults
            fs_options = "autodefrag,compress-force=zstd:2"
        elif disk_info["nvme"] and disk_info["cpu_count"] <= 4:
            # NVMe with low core count - no compression to maximize performance
            fs_options = ""
            # Add discard if TRIM is supported
            if disk_info.get("trim_supported", False):
                fs_options = "discard=async"
        else:
            # SSD defaults
            fs_options = "ssd,compress-force=zstd:1"
            # Add discard if TRIM is supported
            if disk_info.get("trim_supported", False):
                fs_options += ",discard=async"
    
    # Update root mount options with filesystem-wide options
    if fs_options:
        mount_options["/"] = f"{mount_options['/']},{fs_options}"
    
    return mount_options


def _create_directory(path: Path, cmd_runner: CommandRunner) -> None:
    """
    Create directory if it doesn't exist or log that it would be created in simulation mode.
    
    Args:
        path: Directory path to create
        cmd_runner: CommandRunner instance for executing commands
    """
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create directory: {path}")
    else:
        path.mkdir(exist_ok=True, parents=True)


def _mount_filesystem(device: str, mount_point: Path, options: str, cmd_runner: CommandRunner) -> None:
    """
    Mount a filesystem or log that it would be mounted in simulation mode.
    
    Args:
        device: Device path to mount
        mount_point: Path where to mount
        options: Mount options
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        MountError: If mount command fails
    """
    try:
        cmd_runner.run(["mount", "-o", options, device, str(mount_point)])
        logger.info(colorize(f"Mounted {device} to {mount_point} with options: {options}", 
                            TermColors.SUCCESS, cmd_runner.colored_output))
    except subprocess.CalledProcessError as e:
        raise MountError(f"Failed to mount {device} to {mount_point}: {e}")


def mount_filesystems(partitions: PartitionTable, mount_options: MountOptions, args: Any, cmd_runner: CommandRunner) -> None:
    """
    Mount filesystems to target directory.
    Refactored to use helper functions for better code organization.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        mount_options: Dict mapping mount points to their mount options
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        MountError: If there's an error in mounting
    """
    target = args.target
    target_path = Path(target)
    
    # Create target directory if it doesn't exist
    _create_directory(target_path, cmd_runner)
    
    # Define steps for mounting in correct order
    mount_steps = [
        # Step 1: Mount root subvolume
        {
            "action": "mount_root",
            "device": partitions["system"],
            "path": target_path,
            "options": mount_options["/"],
            "subvol": "@"
        },
        
        # Step 2: Create first-level directories
        {
            "action": "create_dirs",
            "directories": ["boot", "home", "opt", "root", "srv", "tmp", "usr", "var"],
            "parent": target_path
        },
        
        # Step 3: Mount boot partition
        {
            "action": "mount",
            "device": partitions["boot"],
            "path": target_path / "boot",
            "options": mount_options["/boot"]
        },
        
        # Step 4: Create and mount boot/efi
        {
            "action": "create_and_mount",
            "device": partitions["efi"],
            "dir_path": target_path / "boot" / "efi",
            "options": mount_options["/boot/efi"]
        },
        
        # Step 5: Mount main subvolumes
        {
            "action": "mount_subvolumes",
            "device": partitions["system"],
            "subvolumes": {
                "@home": "/home",
                "@opt": "/opt",
                "@root": "/root",
                "@srv": "/srv",
                "@tmp": "/tmp",
                "@usr": "/usr",
                "@var": "/var"
            },
            "base_path": target_path,
            "mount_options": mount_options
        },
        
        # Step 6: Create and mount second-level directories under /var
        {
            "action": "create_dirs",
            "directories": ["log", "tmp"],
            "parent": target_path / "var"
        },
        
        # Step 7: Mount var subdirectory subvolumes
        {
            "action": "mount_subvolumes",
            "device": partitions["system"],
            "subvolumes": {
                "@var_log": "/var/log",
                "@var_tmp": "/var/tmp"
            },
            "base_path": target_path,
            "mount_options": mount_options
        }
    ]
    
    # Execute each step
    for step in mount_steps:
        action = step["action"]
        
        if action == "mount_root":
            # Mount root subvolume
            options = step["options"]
            if options == "defaults":
                options = f"subvol={step['subvol']}"
            else:
                options = f"subvol={step['subvol']},{options}"
            
            _mount_filesystem(step["device"], step["path"], options, cmd_runner)
            
        elif action == "create_dirs":
            # Create directories
            for dir_name in step["directories"]:
                dir_path = step["parent"] / dir_name
                _create_directory(dir_path, cmd_runner)
                
        elif action == "mount":
            # Mount a partition
            _mount_filesystem(step["device"], step["path"], step["options"], cmd_runner)
            
        elif action == "create_and_mount":
            # Create a directory and mount in one step
            _create_directory(step["dir_path"], cmd_runner)
            _mount_filesystem(step["device"], step["dir_path"], step["options"], cmd_runner)
            
        elif action == "mount_subvolumes":
            # Mount multiple subvolumes
            for subvol, mountpoint in step["subvolumes"].items():
                rel_path = mountpoint.lstrip("/")
                mount_path = step["base_path"] / rel_path
                
                options = step["mount_options"][mountpoint]
                if options == "defaults":
                    options = f"subvol={subvol}"
                else:
                    options = f"subvol={subvol},{options}"
                
                _mount_filesystem(step["device"], mount_path, options, cmd_runner)
    
    logger.info(colorize("All filesystems mounted successfully", TermColors.SUCCESS, cmd_runner.colored_output))