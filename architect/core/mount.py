"""
Filesystem mounting module.

This module handles mounting filesystems and setting mount options.
"""
import os
import logging
import subprocess
from typing import Dict, Any
from pathlib import Path

from architect.utils.command import CommandRunner, SimulationMode
from architect.core.exceptions import MountError

logger = logging.getLogger('architect')


def determine_mount_options(disk_info: Dict[str, Any], args: Any) -> Dict[str, str]:
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
    mount_options = {
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
        logger.info("Applying hardened mount options according to ANSSI recommendations")
        mount_options.update({
            # In hardened mode, we further restrict some partitions
            "/boot": "defaults,nodev,nosuid,noauto",
            "/var": "defaults,nosuid,nodev,noexec", # Note: This may cause issues with package managers
            # Add hidepid=2 to /proc in fstab separately
        })
        logger.warning("Note: Hardened mode with noexec on /var may require special handling for package management")
    
    # Add discard option for SSD partitions if TRIM is supported
    if not disk_info["rotational"] and disk_info.get("trim_supported", False):
        logger.info("Adding discard mount option for SSD partitions (TRIM supported)")
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


def mount_filesystems(partitions: Dict[str, str], mount_options: Dict[str, str], args: Any, cmd_runner: CommandRunner) -> None:
    """
    Mount filesystems to target directory.
    
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
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create directory: {target_path}")
    else:
        target_path.mkdir(exist_ok=True, parents=True)
    
    # Mount root subvolume
    try:
        options = f"subvol=@,{mount_options['/']}" if mount_options["/"] != "defaults" else "subvol=@"
        cmd_runner.run(["mount", "-o", options, partitions["system"], str(target_path)])
        logger.info(f"Mounted root (/) to {target}")
    except subprocess.CalledProcessError as e:
        raise MountError(f"Failed to mount root subvolume: {e}")
    
    # Create first-level mount points
    mount_points_lvl1 = ["boot", "home", "opt", "root", "srv", "tmp", "usr", "var"]
    for mount_point in mount_points_lvl1:
        mount_path = target_path / mount_point
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
            logger.info(f"Would create directory: {mount_path}")
        else:
            mount_path.mkdir(exist_ok=True)
    
    # Mount boot partition
    try:
        options = mount_options["/boot"]
        boot_path = target_path / "boot"
        cmd_runner.run(["mount", "-o", options, partitions["boot"], str(boot_path)])
        logger.info(f"Mounted boot partition to {boot_path}")
    except subprocess.CalledProcessError as e:
        raise MountError(f"Failed to mount boot partition: {e}")
    
    # Create boot/efi mount point now that boot is mounted
    efi_path = target_path / "boot" / "efi"
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create directory: {efi_path}")
    else:
        efi_path.mkdir(exist_ok=True)
    
    # Mount EFI partition
    try:
        options = mount_options["/boot/efi"]
        cmd_runner.run(["mount", "-o", options, partitions["efi"], str(efi_path)])
        logger.info(f"Mounted EFI partition to {efi_path}")
    except subprocess.CalledProcessError as e:
        raise MountError(f"Failed to mount EFI partition: {e}")
    
    # Mount other subvolumes in correct order
    subvol_mountpoints = {
        "@home": "/home",
        "@opt": "/opt",
        "@root": "/root",
        "@srv": "/srv",
        "@tmp": "/tmp",
        "@usr": "/usr",
        "@var": "/var"
    }
    
    for subvol, mountpoint in subvol_mountpoints.items():
        rel_path = mountpoint.lstrip("/")
        mount_path = target_path / rel_path
        try:
            options = f"subvol={subvol},{mount_options[mountpoint]}" if mount_options[mountpoint] != "defaults" else f"subvol={subvol}"
            cmd_runner.run(["mount", "-o", options, partitions["system"], str(mount_path)])
            logger.info(f"Mounted {subvol} to {mount_path}")
        except subprocess.CalledProcessError as e:
            raise MountError(f"Failed to mount {subvol} to {mountpoint}: {e}")
    
    # Create second-level mount points under /var
    var_log_path = target_path / "var" / "log"
    var_tmp_path = target_path / "var" / "tmp"
    
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create directory: {var_log_path}")
        logger.info(f"Would create directory: {var_tmp_path}")
    else:
        var_log_path.mkdir(exist_ok=True)
        var_tmp_path.mkdir(exist_ok=True)

    # Now mount the second-level subvolumes
    var_subvol_mountpoints = {
        "@var_log": "/var/log",
        "@var_tmp": "/var/tmp"
    }
    
    for subvol, mountpoint in var_subvol_mountpoints.items():
        rel_path = mountpoint.lstrip("/")
        mount_path = target_path / rel_path
        try:
            options = f"subvol={subvol},{mount_options[mountpoint]}" if mount_options[mountpoint] != "defaults" else f"subvol={subvol}"
            cmd_runner.run(["mount", "-o", options, partitions["system"], str(mount_path)])
            logger.info(f"Mounted {subvol} to {mount_path}")
        except subprocess.CalledProcessError as e:
            raise MountError(f"Failed to mount {subvol} to {mountpoint}: {e}")
