"""
Validation utilities.

This module provides functions for validating prerequisites and arguments.
"""
import os
import re
import shutil
import logging
import argparse
from typing import List, Any

from architect.utils.command import CommandRunner, SimulationMode

logger = logging.getLogger('architect')


def check_prerequisites(cmd_runner: CommandRunner, use_real_disk_info: bool = False) -> None:
    """
    Check for required tools and permissions.
    
    Args:
        cmd_runner: CommandRunner instance for executing commands
        use_real_disk_info: Whether real disk info will be accessed even in simulation mode
        
    Raises:
        RuntimeError: If prerequisites are not met
    """
    # Determine if we need to check real prerequisites (either not simulating or using real disk info)
    check_real_prerequisites = (cmd_runner.simulation_mode != SimulationMode.SIMULATE) or use_real_disk_info
    
    # Check if running as root when necessary
    if check_real_prerequisites and os.geteuid() != 0:
        # Different messages based on simulation mode
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
            raise RuntimeError("Root privileges required with --sim-use-real to access disk information")
        else:
            raise RuntimeError("This script must be run as root")
    
    # Required tools for normal operation
    required_tools = [
        "parted", "mkfs.fat", "mkfs.ext4", "mkfs.btrfs", "btrfs",
        "cryptsetup", "blkid", "mount", "umount", "wipefs"
    ]
    
    # Tools required for real disk info detection
    real_disk_detection_tools = [
        "blockdev",    # For getting disk size
        "lsblk"        # For checking disk type and model
    ]
    
    # Optional tools for advanced features
    recommended_tools = [
        "hdparm",   # For TRIM detection on SATA drives
    ]
    
    # Add tools needed for real disk info detection if applicable
    if check_real_prerequisites:
        required_tools.extend(real_disk_detection_tools)
    
    # In pure simulation mode (without real disk info), just log what would be checked
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE and not use_real_disk_info:
        logger.info("Checking for required tools (simulated)")
        for tool in required_tools:
            logger.info(f"Tool '{tool}' would be checked")
        for tool in recommended_tools:
            logger.info(f"Optional tool '{tool}' would be checked")
        return
    
    # Actually check for required tools
    missing_tools = []
    for tool in required_tools:
        if not shutil.which(tool):
            missing_tools.append(tool)
    
    if missing_tools:
        # Different messages based on simulation mode
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
            raise RuntimeError(
                f"Missing required tools for --sim-use-real: {', '.join(missing_tools)}\n"
                "These tools are needed to access real disk information even in simulation mode.\n"
                "Please install the necessary packages for your distribution and try again"
            )
        else:
            raise RuntimeError(
                f"Missing required tools: {', '.join(missing_tools)}\n"
                "Please install the necessary packages for your distribution and try again"
            )
    
    # Check for optional tools and warn if missing
    missing_optional = []
    for tool in recommended_tools:
        if not shutil.which(tool):
            missing_optional.append(tool)
    
    if missing_optional:
        msg = f"Missing optional tools: {', '.join(missing_optional)}\n"
        
        # Different messages based on whether we're using real disk info
        if use_real_disk_info:
            if "nvme" in missing_optional:
                msg += "NVMe detection tools are missing - TRIM detection will be limited for NVMe drives.\n"
            if "hdparm" in missing_optional:
                msg += "SATA SSD detection tools are missing - TRIM detection will be limited for SATA SSDs.\n"
            msg += "Consider installing these tools for better disk detection with --sim-use-real."
        else:
            msg += "These tools are used for advanced features like TRIM detection.\n"
            msg += "The script will still work, but some optimizations may be disabled."
        
        logger.warning(msg)


def normalize_encryption_args(args: Any) -> None:
    """
    Normalize encryption arguments to handle both old and new formats.
    
    Args:
        args: Command line arguments
    """
    # Handle the new encryption argument format
    if hasattr(args, 'hardware_encryption_psid') and hasattr(args, 'hardware_encryption_admin') and hasattr(args, 'hardware_encryption_pass') and any([args.hardware_encryption_psid, args.hardware_encryption_admin, args.hardware_encryption_pass]):
        # Convert to the legacy format for compatibility with the rest of the code
        args.hardware_encryption = (
            args.hardware_encryption_psid or "none",
            args.hardware_encryption_admin or "",
            args.hardware_encryption_pass or ""
        )


def validate_encryption_requirements(args: Any, cmd_runner: CommandRunner) -> None:
    """
    Validate encryption requirements and check cryptsetup version.
    
    Args:
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        EncryptionError: If requirements are not met
    """
    from architect.core.exceptions import EncryptionError
    
    # Check cryptsetup version if encryption is requested
    if hasattr(args, 'hardware_encryption') and hasattr(args, 'software_encryption') and (args.hardware_encryption or args.software_encryption or any([
        getattr(args, 'hardware_encryption_psid', None),
        getattr(args, 'hardware_encryption_admin', None),
        getattr(args, 'hardware_encryption_pass', None)
    ])):
        try:
            result = cmd_runner.run(["cryptsetup", "--version"], check=False)
            version_str = result.stdout.strip()
            version_match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_str)
            
            if version_match:
                major, minor, patch = map(int, version_match.groups())
                if (args.hardware_encryption or getattr(args, 'hardware_encryption_pass', None)) and (major < 2 or (major == 2 and minor < 6)):
                    raise EncryptionError(
                        f"Opal hardware encryption requires cryptsetup 2.6.0 or newer.\n"
                        f"Found version: {version_str}\n"
                        "Please upgrade cryptsetup and try again."
                    )
        except Exception as e:
            logger.warning(f"Could not check cryptsetup version: {e}")
            logger.warning("Continuing anyway, but hardware encryption might fail")
