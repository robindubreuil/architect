"""
crypttab generation module.

This module handles generating crypttab entries for encrypted partitions.
Improved with shared functions and better error handling.
"""
import os
import logging
from typing import Dict, Any
from pathlib import Path

from architect.utils.command import CommandRunner, SimulationMode
from architect.utils.format import TermColors, colorize
from architect.utils.types import DiskInfo, PartitionTable
from architect.core.exceptions import CrypttabError

logger = logging.getLogger('architect')


def _create_etc_directory(target_path: Path, cmd_runner: CommandRunner) -> None:
    """
    Create the /etc directory in the target if it doesn't exist.
    
    Args:
        target_path: Path to the target directory
        cmd_runner: CommandRunner instance for executing commands
    """
    etc_path = target_path / "etc"
    
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create directory: {etc_path}")
    else:
        etc_path.mkdir(exist_ok=True)


def generate_crypttab(partitions: PartitionTable, disk_info: DiskInfo, args: Any, cmd_runner: CommandRunner) -> None:
    """
    Generate crypttab in target directory.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        disk_info: Dict containing disk info
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        CrypttabError: If there's an error in crypttab generation
    """
    if not args.generate_crypttab or "system_crypt" not in partitions:
        return
    
    target = args.target
    target_path = Path(target)
    etc_path = target_path / "etc"
    crypttab_path = etc_path / "crypttab"
    
    # Create etc directory if it doesn't exist
    _create_etc_directory(target_path, cmd_runner)
    
    logger.info(colorize(f"Generating crypttab at {crypttab_path}", 
                        TermColors.INFO, cmd_runner.colored_output))
    
    try:
        # Get device PARTUUID for the encrypted partition
        try:
            result = cmd_runner.run(["blkid", "-s", "PARTUUID", "-o", "value", partitions["system_crypt"]])
            encrypted_partuuid = result.stdout.strip()
        except Exception as e:
            logger.error(colorize(f"Failed to get PARTUUID for {partitions['system_crypt']}: {e}", 
                                 TermColors.ERROR, cmd_runner.colored_output))
            raise
            
        luks_name = os.path.basename(partitions["system"])
        
        # Build crypttab content
        crypttab_content = []
        crypttab_content.append("# /etc/crypttab: mappings for encrypted partitions.")
        crypttab_content.append("# Generated by architect")
        crypttab_content.append("#")
        crypttab_content.append("# <target name> <source device> <key file> <options>")
        
        # Determine crypttab options based on disk type
        options = ["luks", "timeout=180"]
        
        # Add discard only for SSDs with TRIM support
        if not disk_info["rotational"] and disk_info.get("trim_supported", False):
            logger.info("Adding discard option to crypttab (SSD with TRIM support)")
            options.append("discard")
        elif not disk_info["rotational"]:
            logger.info("SSD detected but TRIM support not confirmed, not adding discard option to crypttab")
        
        # Join options with commas
        options_str = ",".join(options)
        
        # Add line for our LUKS device
        crypttab_content.append(f"{luks_name} PARTUUID={encrypted_partuuid} none {options_str}")
        
        # Write crypttab or display it in simulation mode
        if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
            logger.info("Would write the following to crypttab:")
            for line in crypttab_content:
                logger.info(f"  {line}")
        else:
            with open(crypttab_path, "w") as f:
                f.write("\n".join(crypttab_content) + "\n")
        
        logger.info(colorize("crypttab generated successfully", 
                            TermColors.SUCCESS, cmd_runner.colored_output))
    except Exception as e:
        error_msg = f"Failed to generate crypttab: {e}"
        logger.error(colorize(error_msg, TermColors.ERROR, cmd_runner.colored_output))
        raise CrypttabError(error_msg)