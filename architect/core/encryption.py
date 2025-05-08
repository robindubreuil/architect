"""
Disk encryption module.

This module handles disk encryption using LUKS and hardware-based encryption.
"""
import logging
import subprocess
from typing import Dict, List, Any

from architect.utils.command import CommandRunner
from architect.core.exceptions import EncryptionError

logger = logging.getLogger('architect')


def reset_opal_drive(disk: str, psid: str, cmd_runner: CommandRunner) -> None:
    """
    Reset an Opal drive with the provided PSID.
    This function should be called before any disk modifications.
    
    Args:
        disk: Path to the disk device
        psid: PSID for factory reset
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        EncryptionError: If the reset fails
    """
    logger.info("Resetting Opal drive with PSID")
    
    try:
        run_cryptsetup_cmd(
            ["cryptsetup", "erase", "--hw-opal-factory-reset", disk],
            f"{psid}\nYES\n",  # Auto-confirm with YES
            cmd_runner
        )
        logger.info("Opal drive reset successful")
    except Exception as e:
        raise EncryptionError(f"Failed to reset Opal drive: {e}")


def run_cryptsetup_cmd(cmd: List[str], secret_input: str, cmd_runner: CommandRunner) -> None:
    """
    Run a cryptsetup command with the provided secret input.
    
    Args:
        cmd: The cryptsetup command to run
        secret_input: Secret input to provide to the command
        cmd_runner: CommandRunner instance for executing commands
        
    Raises:
        EncryptionError: If the command fails
    """
    try:
        cmd_runner.run(cmd, input=secret_input)
    except subprocess.CalledProcessError as e:
        raise EncryptionError(f"Cryptsetup command failed: {e.stderr if hasattr(e, 'stderr') else str(e)}")


def setup_encryption(disk: str, partitions: Dict[str, str], args: Any, cmd_runner: CommandRunner) -> Dict[str, str]:
    """
    Set up encryption for the system partition using cryptsetup for both
    hardware (Opal) and software (LUKS) encryption.
    
    Args:
        partitions: Dict mapping partition roles to device paths
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
        
    Returns:
        Updated partitions dict with encrypted device path
        
    Raises:
        EncryptionError: If there's an error in encryption setup
    """
    system_partition = partitions["system"]
    mapped_partitions = partitions.copy()
    
    # Determine encryption mode based on arguments
    hw_only = args.hardware_encryption and not args.software_encryption
    hw_and_sw = args.hardware_encryption and args.software_encryption
    sw_only = not args.hardware_encryption and args.software_encryption
    
    luks_name = "luks-root"
    luks_device = f"/dev/mapper/{luks_name}"
    
    try:
        # Setup based on encryption mode
        if hw_only:
            # Hardware-only encryption (Opal)
            psid, admin_secret, luks_secret = args.hardware_encryption
            logger.info("Setting up hardware-only encryption (Opal 2.0)")
            
            run_cryptsetup_cmd(
                ["cryptsetup", "luksFormat", "--type", "luks2", "--hw-opal-only", disk],
                f"{luks_secret}\n{luks_secret}\n{admin_secret}\n{admin_secret}\n",
                cmd_runner
            )
            
        elif hw_and_sw:
            # Combined hardware (Opal) and software (LUKS) encryption
            psid, admin_secret, luks_secret = args.hardware_encryption
            logger.info("Setting up combined hardware (Opal) and software (LUKS) encryption")
            
            run_cryptsetup_cmd(
                [
                    "cryptsetup", "luksFormat", "--type", "luks2", "--hw-opal", 
                    "--cipher", "aes-xts-plain64", "--key-size", "512",
                    "--hash", "sha512", "--pbkdf", "argon2id", "--iter-time", "5000",
                    system_partition
                ],
                f"{luks_secret}\n{luks_secret}\n{admin_secret}\n{admin_secret}\n",
                cmd_runner
            )
            
        elif sw_only:
            # Software-only encryption (LUKS)
            luks_secret = args.software_encryption
            logger.info("Setting up software-only encryption (LUKS)")
            
            run_cryptsetup_cmd(
                [
                    "cryptsetup", "luksFormat", "--type", "luks2",
                    "--cipher", "aes-xts-plain64", "--key-size", "512",
                    "--hash", "sha512", "--pbkdf", "argon2id", "--iter-time", "5000",
                    system_partition
                ],
                f"{luks_secret}\n{luks_secret}\n",  # Double input for confirmation
                cmd_runner
            )
        
        # Open the LUKS container for all encryption methods
        if hw_only or hw_and_sw:
            psid, admin_secret, luks_secret = args.hardware_encryption
            run_cryptsetup_cmd(
                ["cryptsetup", "open", system_partition, luks_name],
                f"{luks_secret}\n",
                cmd_runner
            )
        elif sw_only:
            luks_secret = args.software_encryption
            run_cryptsetup_cmd(
                ["cryptsetup", "open", system_partition, luks_name],
                f"{luks_secret}\n",
                cmd_runner
            )
        
        # Update the system partition to point to the LUKS device
        if hw_only or hw_and_sw or sw_only:
            mapped_partitions["system"] = luks_device
            mapped_partitions["system_crypt"] = system_partition
            logger.info(f"Encryption set up successfully for {system_partition}")
        
    except EncryptionError as e:
        raise EncryptionError(f"Failed to set up encryption: {e}")
    
    return mapped_partitions