"""
Disk information and validation module.

This module provides functions for querying disk information and validating
disk availability with improved type safety and optimized code.
"""
import os
import logging
import shutil
from typing import Dict, Any, Optional

from architect.utils.command import CommandRunner, SimulationMode
from architect.utils.types import DiskInfo
from architect.utils.format import TermColors, colorize
from architect.core.exceptions import DiskNotFoundError

logger = logging.getLogger('architect')


def read_sysfs_value(path: str, default: Optional[str] = None) -> str:
    """
    Safely read a value from sysfs.
    
    Args:
        path: Path to the sysfs file
        default: Default value if file doesn't exist or can't be read
        
    Returns:
        Content of the file as string or default
    """
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return f.read().strip()
    except Exception as e:
        logger.debug(f"Could not read {path}: {e}")
    
    return default or ""


def is_disk_available(disk: str, cmd_runner: CommandRunner) -> bool:
    """
    Check if the disk exists and is a block device.
    
    Args:
        disk: Path to the disk device
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        True if disk exists and is a block device, False otherwise
    """
    # In pure simulation mode, assume disk is available
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE and not cmd_runner.use_real_disk_info:
        return True
        
    # Check if disk exists
    if not os.path.exists(disk):
        return False
    
    try:
        # Use the appropriate command function based on mode
        cmd_func = (cmd_runner.run_real if cmd_runner.simulation_mode == SimulationMode.SIMULATE 
                    and cmd_runner.use_real_disk_info else cmd_runner.run)
        
        result = cmd_func(["lsblk", "-n", "-o", "TYPE", disk], check=False)
        return "disk" in result.stdout.lower()
    except Exception as e:
        logger.warning(colorize(f"Error checking if disk is available: {e}", 
                               TermColors.WARNING, cmd_runner.colored_output))
        return False


def check_trim_support(disk: str, is_ssd: bool, cmd_runner: CommandRunner) -> bool:
    """
    Check if the disk device supports TRIM/discard commands.
    
    Args:
        disk: Path to the disk device
        is_ssd: Whether the disk is an SSD/NVMe (non-rotational)
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        True if TRIM is supported, False otherwise
    """
    # If not SSD, no TRIM support
    if not is_ssd:
        return False
        
    disk_name = os.path.basename(disk)
    
    # Simulation mode handling
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        if "trim_supported" in cmd_runner.simulation_params:
            trim_supported = cmd_runner.simulation_params["trim_supported"]
            logger.info(f"Simulation: disk configured with TRIM support: {trim_supported}")
            return trim_supported
        # In simulation, assume modern SSDs support TRIM
        return True
    
    # NVMe detection - all modern NVMe drives support TRIM
    if "nvme" in disk_name:
        logger.info(colorize("NVMe drive detected - assuming TRIM support", 
                             TermColors.INFO, cmd_runner.colored_output))
        return True
    
    # For SATA/other disk types, try hdparm if available
    if shutil.which("hdparm"):
        try:
            result = cmd_runner.run(["hdparm", "-I", disk], check=False)
            return "TRIM supported" in result.stdout
        except Exception as e:
            logger.warning(colorize(f"Error checking TRIM support: {e}", 
                                   TermColors.WARNING, cmd_runner.colored_output))
    else:
        logger.debug("hdparm not found for TRIM detection")
        
    # Default assumption for modern SSDs
    return True


def get_disk_info(disk: str, cmd_runner: CommandRunner) -> DiskInfo:
    """
    Get information about the disk with simplified logic and better type safety.
    
    Args:
        disk: Path to the disk device
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        DiskInfo object containing disk information
        
    Raises:
        DiskNotFoundError: If disk is not found
    """
    # Check if disk exists (except in simulation mode)
    if not is_disk_available(disk, cmd_runner) and cmd_runner.simulation_mode != SimulationMode.SIMULATE:
        raise DiskNotFoundError(f"Disk {disk} not found or is not a block device")
    
    # Initialize defaults
    disk_name = os.path.basename(disk)
    is_nvme = "nvme" in disk_name.lower()
    
    # Initialize disk_info with default values
    disk_info = DiskInfo(
        size_bytes=0,
        size_gib=0.0,
        rotational=True,
        nvme=is_nvme,
        model="Unknown",
        trim_supported=False,
        cpu_count=os.cpu_count() or 4
    )
    
    # Determine which method to use based on mode
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        if cmd_runner.use_real_disk_info:
            _get_real_disk_info(disk, disk_name, disk_info, cmd_runner)
        else:
            _get_simulated_disk_info(disk, disk_name, disk_info, cmd_runner)
    else:
        _get_real_disk_info(disk, disk_name, disk_info, cmd_runner)
    
    # Set TRIM support based on disk type
    if not disk_info["rotational"]:
        disk_info["trim_supported"] = check_trim_support(
            disk, is_ssd=not disk_info["rotational"], cmd_runner=cmd_runner
        )
    
    return disk_info


def _get_real_disk_info(disk: str, disk_name: str, disk_info: DiskInfo, cmd_runner: CommandRunner) -> None:
    """
    Get real disk information from the system.
    
    Args:
        disk: Path to the disk device
        disk_name: Base name of the disk
        disk_info: DiskInfo object to populate
        cmd_runner: CommandRunner instance for executing commands
    """
    # Use appropriate command function based on mode
    cmd_func = (cmd_runner.run_real if cmd_runner.simulation_mode == SimulationMode.SIMULATE 
                else cmd_runner.run)
    
    # Get disk size
    try:
        result = cmd_func(["blockdev", "--getsize64", disk])
        disk_info["size_bytes"] = int(result.stdout.strip())
        disk_info["size_gib"] = disk_info["size_bytes"] / (1024**3)
        logger.info(f"Disk size: {disk_info['size_gib']:.2f} GiB")
    except Exception as e:
        logger.warning(colorize(f"Error getting disk size: {e}", 
                               TermColors.WARNING, cmd_runner.colored_output))
        disk_info["size_bytes"] = 500107862016  # Default ~465.76 GiB
        disk_info["size_gib"] = disk_info["size_bytes"] / (1024**3)
    
    # Check if the disk is rotational (HDD) or non-rotational (SSD/NVMe)
    rotational = read_sysfs_value(f"/sys/block/{disk_name}/queue/rotational", "1")
    disk_info["rotational"] = rotational == "1"
    
    # Get disk model
    try:
        result = cmd_func(["lsblk", "-n", "-o", "MODEL", disk], check=False)
        disk_info["model"] = result.stdout.strip() or f"{'NVMe' if disk_info['nvme'] else 'SSD/HDD'}"
    except Exception as e:
        logger.warning(colorize(f"Error getting disk model: {e}", 
                               TermColors.WARNING, cmd_runner.colored_output))


def _get_simulated_disk_info(disk: str, disk_name: str, disk_info: DiskInfo, cmd_runner: CommandRunner) -> None:
    """
    Generate simulated disk information.
    
    Args:
        disk: Path to the disk device
        disk_name: Base name of the disk
        disk_info: DiskInfo object to populate
        cmd_runner: CommandRunner instance for executing commands
    """
    params = cmd_runner.simulation_params
    
    # Disk size
    if "disk_size" in params:
        from architect.utils.format import parse_size_spec
        try:
            # Reference size for parsing
            total_size = 10 * 1024**4  # 10 TiB
            disk_info["size_bytes"] = parse_size_spec(params["disk_size"], total_size)
        except ValueError:
            disk_info["size_bytes"] = 500107862016  # Default ~465.76 GiB
    else:
        disk_info["size_bytes"] = 500107862016  # Default ~465.76 GiB
        
    disk_info["size_gib"] = disk_info["size_bytes"] / (1024**3)
    
    # Rotational flag
    disk_info["rotational"] = params.get("rotational", False)
    
    # NVMe flag - keep the value set during initialization if not in params
    if "nvme" in params:
        disk_info["nvme"] = params["nvme"]
        
    # Model name
    disk_type = params.get("disk_type", "ssd" if not disk_info["rotational"] else "hdd")
    disk_info["model"] = f"SIMULATED {disk_type.upper()}"