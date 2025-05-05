"""
Filesystem creation and management module with parallel processing support.

This module handles filesystem creation and btrfs subvolume setup.
"""
import os
import logging
import subprocess
import tempfile
from typing import Dict, Any, List, Tuple, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from architect.utils.command import CommandRunner, SimulationMode
from architect.core.exceptions import FilesystemError

logger = logging.getLogger('architect')


def _create_filesystem(
    filesystem_type: str, 
    device: str, 
    label: str, 
    cmd_runner: CommandRunner
) -> Tuple[str, str, bool]:
    """
    Create a single filesystem on a partition.
    
    Args:
        filesystem_type: Type of filesystem to create (fat, ext4, btrfs)
        device: Device path to create filesystem on
        label: Label for the filesystem
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Tuple of (device, filesystem_type, success)
    """
    try:
        if filesystem_type == "fat":
            cmd_runner.run(["mkfs.fat", "-F32", "-n", label, device])
            logger.info(f"Created FAT32 filesystem on {device}")
        elif filesystem_type == "ext4":
            cmd_runner.run(["mkfs.ext4", "-L", label, device])
            logger.info(f"Created ext4 filesystem on {device}")
        elif filesystem_type == "btrfs":
            cmd_runner.run(["mkfs.btrfs", "-L", label, device])
            logger.info(f"Created btrfs filesystem on {device}")
        else:
            logger.error(f"Unsupported filesystem type: {filesystem_type}")
            return (device, filesystem_type, False)
            
        return (device, filesystem_type, True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to create {filesystem_type} filesystem on {device}: {e}")
        return (device, filesystem_type, False)


def create_filesystems(
    partitions: Dict[str, str], 
    disk_info: Dict[str, Any], 
    args: Any, 
    cmd_runner: CommandRunner
) -> None:
    """
    Create filesystems on partitions in parallel.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        disk_info: Dict containing disk info
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        FilesystemError: If there's an error in filesystem creation
    """
    logger.info("Creating filesystems in parallel")
    
    # Define filesystem creation tasks
    fs_tasks = [
        ("fat", partitions["efi"], "ESP"),           # FAT32 for EFI
        ("ext4", partitions["boot"], "boot"),        # ext4 for boot
        ("btrfs", partitions["system"], "root"),   # btrfs for system
    ]
    
    # Set maximum number of workers based on CPU count with reasonable limits
    max_workers = min(len(fs_tasks), disk_info.get("cpu_count", os.cpu_count() or 2))
    
    # In simulation mode, reduce to 1 worker to simplify output
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        max_workers = 1
    
    failed_tasks = []
    
    # Execute filesystem creation in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_fs = {
            executor.submit(_create_filesystem, fs_type, device, label, cmd_runner): 
            (fs_type, device)
            for fs_type, device, label in fs_tasks
        }
        
        # Process results as they complete
        for future in as_completed(future_to_fs):
            device, fs_type, success = future.result()
            if not success:
                fs_info = future_to_fs[future]
                failed_tasks.append(fs_info)
    
    # If any tasks failed, raise an error
    if failed_tasks:
        failed_info = ", ".join([f"{fs_type} on {device}" for fs_type, device in failed_tasks])
        raise FilesystemError(
            f"Failed to create filesystem(s): {failed_info}"
        )
    
    logger.info("All filesystems created successfully")


def create_btrfs_subvolumes(partitions: Dict[str, str], args: Any, cmd_runner: CommandRunner) -> Dict[str, str]:
    """
    Create btrfs subvolumes and set @ as the default subvolume.
    
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
        
        # Set @ as the default subvolume for a DPS friendly behavior
        try:
            # Obtenir l'ID du subvolume @ directement avec la commande show
            root_subvol_path = os.path.join(temp_dir, "@")
            result = cmd_runner.run(["btrfs", "subvolume", "show", root_subvol_path])
            
            # Extraire l'ID du subvolume des informations
            root_subvol_id = None
            for line in result.stdout.strip().split('\n'):
                if line.strip().startswith('Subvolume ID:'):
                    root_subvol_id = line.split(':')[1].strip()
                    break
            
            if root_subvol_id:
                cmd_runner.run(["btrfs", "subvolume", "set-default", root_subvol_id, temp_dir])
                logger.info(f"Set @ (ID: {root_subvol_id}) as the default subvolume")
            else:
                raise FilesystemError("Could not extract subvolume ID from btrfs output")
        except subprocess.CalledProcessError as e:
            raise FilesystemError(f"Failed to set @ as the default subvolume: {e}")
        
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
