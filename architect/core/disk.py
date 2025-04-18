"""
Disk information and validation module.

This module provides functions for querying disk information and validating
disk availability.
"""
import os
import logging
import shutil
from typing import Dict, Any

from architect.utils.command import CommandRunner, SimulationMode
from architect.core.exceptions import DiskNotFoundError

logger = logging.getLogger('architect')


def is_disk_available(disk: str, cmd_runner: CommandRunner) -> bool:
    """
    Check if the disk exists and is a block device.
    
    Args:
        disk: Path to the disk device
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        True if disk exists and is a block device, False otherwise
    """
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE and not cmd_runner.use_real_disk_info:
        # In pure simulation mode, assume disk is available
        return True
        
    # Check if disk exists
    if not os.path.exists(disk):
        return False
    
    try:
        # Use run_real if in simulation mode but want real info
        cmd = ["lsblk", "-n", "-o", "TYPE", disk]
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE and cmd_runner.use_real_disk_info:
            result = cmd_runner.run_real(cmd, check=False)
        else:
            result = cmd_runner.run(cmd, check=False)
            
        return "disk" in result.stdout.lower()
    except Exception as e:
        logger.warning(f"Error checking if disk is available: {e}")
        return False


def check_trim_support(disk: str, cmd_runner: CommandRunner) -> bool:
    """
    Check if the disk device supports TRIM/discard commands.
    
    Args:
        disk: Path to the disk device
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        True if TRIM is supported, False otherwise
    """
    disk_name = os.path.basename(disk)
    
    # If in simulation mode
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        # Use simulation parameter if available
        if "trim_supported" in cmd_runner.simulation_params:
            trim_supported = cmd_runner.simulation_params["trim_supported"]
            logger.info(f"Simulation: disk configured with TRIM support: {trim_supported}")
            return trim_supported
            
        # If we want to use real disk characteristics but can't determine, use default
        if cmd_runner.use_real_disk_info:
            logger.info(f"Simulation: using real disk characteristics for TRIM detection")
        else:
            # Default value for simulation: assume SSDs support TRIM
            logger.info(f"Simulation: assuming the disk supports TRIM if it's non-rotational")
            return True
    
    # ---- SIMPLIFIED TRIM DETECTION APPROACH ----
    
    # For NVMe devices - simplest possible approach
    if "nvme" in disk_name:
        logger.info(f"Detected NVMe disk: {disk}")
        # Modern NVMe drives almost universally support TRIM
        # Skip any complicated detection that might fail with binary output
        
        # Note: All modern NVMe drives from the last several years support TRIM/DSM
        # There's very little practical reason to go through complex detection
        # that might fail due to encoding issues with binary output
        logger.info("NVMe drive detected - assuming TRIM support (standard for modern NVMe)")
        return True
    
    # For SATA/other disk types
    try:
        # First try with lsblk to check if disk is SSD (non-rotational)
        is_ssd = False
        
        # Check if the disk is rotational (HDD) or non-rotational (SSD)
        sys_path = f"/sys/block/{disk_name}/queue/rotational"
        if os.path.exists(sys_path):
            try:
                with open(sys_path, "r") as f:
                    rotational = f.read().strip()
                    is_ssd = rotational == "0"
                logger.info(f"Disk {disk} is {'SSD' if is_ssd else 'HDD'} (rotational={rotational})")
            except Exception as e:
                logger.warning(f"Error reading rotational flag from sysfs: {e}")
        
        # If it's not an SSD, TRIM is not supported
        if not is_ssd:
            logger.info(f"Disk {disk} is rotational (HDD), TRIM not supported")
            return False
            
        # For SSDs, try to check TRIM support with hdparm
        if shutil.which("hdparm"):
            # Use run_real if in simulation mode but want real info
            cmd = ["hdparm", "-I", disk]
            if cmd_runner.simulation_mode == SimulationMode.SIMULATE and cmd_runner.use_real_disk_info:
                result = cmd_runner.run_real(cmd, check=False)
            else:
                result = cmd_runner.run(cmd, check=False)
                
            trim_supported = "TRIM supported" in result.stdout
            logger.info(f"TRIM support for {disk}: {trim_supported} (via hdparm)")
            return trim_supported
        else:
            logger.warning("hdparm command not found - cannot detect TRIM support for SATA drives")
            logger.warning("Assuming modern SSD supports TRIM")
            return True
            
    except Exception as e:
        logger.warning(f"Error checking TRIM support for {disk}: {e}")
        logger.warning("Assuming modern SSD supports TRIM as fallback")
        # Default to assuming SSD supports TRIM (reasonable for modern SSDs)
        return is_ssd
    

def get_disk_info(disk: str, cmd_runner: CommandRunner) -> Dict[str, Any]:
    """
    Get information about the disk.
    
    Args:
        disk: Path to the disk device
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Dict containing disk info (size, rotational, model, etc.)
        
    Raises:
        DiskNotFoundError: If disk is not found
    """
    # Check if disk exists (except in simulation mode)
    if not is_disk_available(disk, cmd_runner) and cmd_runner.simulation_mode != SimulationMode.SIMULATE:
        raise DiskNotFoundError(f"Disk {disk} not found or is not a block device")
    
    disk_info = {}
    disk_name = os.path.basename(disk)
    
    # Get disk size
    try:
        # If in simulation mode but want to use real disk
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE and cmd_runner.use_real_disk_info:
            if os.path.exists(disk):
                logger.info(f"Simulation: using real disk information for {disk}")
                try:
                    if not shutil.which("blockdev"):
                        raise RuntimeError("blockdev command not found")
                    
                    result = cmd_runner.run_real(["blockdev", "--getsize64", disk])
                    disk_info["size_bytes"] = int(result.stdout.strip())
                except Exception as e:
                    logger.warning(f"Could not get real disk size: {e}")
                    disk_info["size_bytes"] = 500107862016  # Fallback to ~465.76 GiB
            else:
                logger.warning(f"Cannot use real disk info: disk {disk} does not exist")
                disk_info["size_bytes"] = 500107862016
        else:
            result = cmd_runner.run(["blockdev", "--getsize64", disk])
            disk_info["size_bytes"] = int(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Error getting disk size, using default value: {e}")
        disk_info["size_bytes"] = 500107862016
        
    disk_info["size_gib"] = disk_info["size_bytes"] / (1024**3)  # Binary unit (GiB)
    
    # Check if the disk is rotational (HDD) or non-rotational (SSD/NVMe)
    sys_path = f"/sys/block/{disk_name}/queue/rotational"
    
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        if cmd_runner.use_real_disk_info and os.path.exists(sys_path):
            try:
                with open(sys_path, "r") as f:
                    rotational = f.read().strip()
                    disk_info["rotational"] = rotational == "1"
                logger.info(f"Using real rotational flag: {disk_info['rotational']}")
            except Exception as e:
                logger.warning(f"Error reading rotational flag: {e}")
                if "rotational" in cmd_runner.simulation_params:
                    disk_info["rotational"] = cmd_runner.simulation_params["rotational"]
                else:
                    disk_info["rotational"] = False
        elif "rotational" in cmd_runner.simulation_params:
            disk_info["rotational"] = cmd_runner.simulation_params["rotational"]
        else:
            disk_info["rotational"] = False
    else:
        if os.path.exists(sys_path):
            with open(sys_path, "r") as f:
                rotational = f.read().strip()
                disk_info["rotational"] = rotational == "1"
        else:
            disk_info["rotational"] = False
    
    # Check if disk is NVMe
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE and "nvme" in cmd_runner.simulation_params:
        disk_info["nvme"] = cmd_runner.simulation_params["nvme"]
    else:
        disk_info["nvme"] = "nvme" in disk_name.lower()
    
    # Check TRIM support
    disk_info["trim_supported"] = check_trim_support(disk, cmd_runner) if not disk_info["rotational"] else False
    
    # Get CPU core count for optimizing btrfs options
    disk_info["cpu_count"] = os.cpu_count() or 4  # Default to 4 if we can't determine
    
    # Get disk model
    try:
        if not shutil.which("lsblk") and cmd_runner.simulation_mode == SimulationMode.SIMULATE and cmd_runner.use_real_disk_info:
            raise RuntimeError("lsblk command not found")
            
        cmd = ["lsblk", "-n", "-o", "MODEL", disk]
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE and cmd_runner.use_real_disk_info:
            result = cmd_runner.run_real(cmd, check=False)
        else:
            result = cmd_runner.run(cmd, check=False)
            
        disk_info["model"] = result.stdout.strip() or "Unknown"
    except Exception as e:
        logger.warning(f"Error getting disk model: {e}")
        disk_info["model"] = "Unknown"
    
    return disk_info