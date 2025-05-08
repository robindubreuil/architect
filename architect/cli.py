"""
Command-line interface for architect.

This module handles argument parsing and orchestrates the disk preparation process.
"""
import argparse
import logging
import os
import sys
from typing import Dict, List, Optional, Any

from architect.utils.logging import setup_logging
from architect.utils.command import CommandRunner, SimulationMode, TermColors
from architect.utils.format import bytes_to_human_readable
from architect.utils.validation import check_prerequisites, normalize_encryption_args, validate_encryption_requirements
from architect.core.disk import get_disk_info, is_disk_available
from architect.core.partition import prepare_disk
from architect.core.encryption import setup_encryption
from architect.core.filesystem import create_filesystems, create_btrfs_subvolumes
from architect.core.mount import determine_mount_options, mount_filesystems
from architect.config.fstab import generate_fstab
from architect.config.crypttab import generate_crypttab
from architect.core.exceptions import (
    DiskNotFoundError, NotEnoughSpaceError, PartitioningError, 
    EncryptionError, FilesystemError, MountError, FstabError, CrypttabError
)

logger = logging.getLogger('architect')

# Constants
DEFAULT_TARGET = "/target"


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.
    
    Returns:
        Namespace containing parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Disk preparation and partitioning tool for secure Linux installation"
    )
    
    parser.add_argument(
        "disk",
        help="Target disk device (e.g., /dev/sda, /dev/nvme0n1)"
    )
    
    parser.add_argument(
        "--hardened",
        action="store_true",
        help="Activate hardening profile for mount options according to ANSSI security recommendations"
    )
    
    # Add help text for size specification in arguments
    size_help_text = "(can use binary units like GiB, MiB or decimal units like GB, MB)"
    
    parser.add_argument(
        "-o", "--overprovision",
        help=f"Reserve space at the end of the drive for overprovisioning (in %% of whole disk or specific size) {size_help_text}"
    )
    
    parser.add_argument(
        "-w", "--windows",
        help=f"Reserve and prepare space for a Windows installation (in %% of whole disk or in GiB) {size_help_text}"
    )
    
    # Improved encryption options
    encryption_group = parser.add_argument_group('Encryption options')
    encryption_group.add_argument(
        "--hardware-encryption-psid",
        help="PSID for factory reset of OPAL drive (WARNING: erases ALL data)"
    )
    
    encryption_group.add_argument(
        "--hardware-encryption-admin",
        help="Admin password for OPAL hardware encryption"
    )
    
    encryption_group.add_argument(
        "--hardware-encryption-pass",
        help="Passphrase for OPAL/LUKS encryption"
    )
    
    # For backward compatibility
    encryption_group.add_argument(
        "--hardware-encryption",
        dest="hardware_encryption",
        nargs=3,
        metavar=("PSID", "ADMIN_SECRET", "LUKS_SECRET"),
        help="Use hardware encryption (Opal 2.0) for the system partition (legacy format)"
    )
    
    encryption_group.add_argument(
        "--software-encryption",
        dest="software_encryption",
        metavar="LUKS_SECRET",
        help="Use software encryption (dm-crypt) for the system partition"
    )
    
    parser.add_argument(
        "-t", "--target",
        default=DEFAULT_TARGET,
        help=f"Mount point for the target root (default: {DEFAULT_TARGET})"
    )
    
    parser.add_argument(
        "-f", "--generate-fstab",
        action="store_true",
        help="Generate an optimized fstab to /etc/fstab in the target root"
    )
    
    parser.add_argument(
        "-c", "--generate-crypttab",
        action="store_true",
        help="Generate a crypttab to /etc/crypttab in the target root for encrypted partitions"
    )
    
    parser.add_argument(
        "-v", "--btrfs-options",
        help="Additional filesystem-wide mount options for the system partition"
    )
    
    # Option for forcing TRIM/discard
    parser.add_argument(
        "--force-discard",
        action="store_true",
        help="Force enable TRIM/discard for all SSD operations, even if TRIM support cannot be confirmed"
    )

    # Simulation options
    parser.add_argument(
        "-s", "--simulate",
        action="store_true",
        help="Simulate operations without making any changes to the system"
    )
    
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output in simulation mode"
    )
    
    simulation_group = parser.add_argument_group('Disk simulation options (only with --simulate)')
    simulation_group.add_argument(
        "--sim-disk-size",
        help="Simulated disk size (e.g., '500G', '1T') - only used in simulation mode"
    )
    
    simulation_group.add_argument(
        "--sim-disk-type",
        choices=["hdd", "ssd", "nvme"],
        help="Simulated disk type (hdd, ssd, nvme) - only used in simulation mode"
    )
    
    simulation_group.add_argument(
        "--sim-disk-trim",
        choices=["yes", "no"],
        help="Simulate TRIM support (yes, no) - only used in simulation mode"
    )
    
    simulation_group.add_argument(
        "--sim-use-real",
        action="store_true",
        help="Use characteristics of the real disk, even in simulation mode"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true", 
        help="Enable debug logging"
    )

    parser.add_argument(
    "--target-arch",
    choices=["x86_64", "arm64", "ia64", "arm", "x86"],
    help="Force target architecture for Linux system partition type"
    )
    
    return parser.parse_args()


def display_simulation_summary(args: argparse.Namespace, cmd_runner: CommandRunner) -> None:
    """
    Display a summary of the simulation.
    
    Args:
        args: Command line arguments
        cmd_runner: CommandRunner instance for executing commands
    """
    if cmd_runner.simulation_mode != SimulationMode.SIMULATE:
        return
    
    # Get the simulation report
    report = cmd_runner.get_simulation_report()
    
    # Get terminal width
    try:
        terminal_width = os.get_terminal_size().columns
    except (AttributeError, OSError):
        terminal_width = 80
    
    # Add a line of stars
    stars = "*" * terminal_width
    
    # Import TermColors from format
    from architect.utils.format import TermColors, colorize
    
    # Print the report with decorations
    if cmd_runner.colored_output:
        print(f"\n{colorize(stars, TermColors.SIM)}")
        print(colorize(f"SIMULATION COMPLETE - NO CHANGES WERE MADE", TermColors.SIM + TermColors.BOLD))
        print(f"{colorize(stars, TermColors.SIM)}\n")
        
        print(colorize("The following operations would have been performed:", TermColors.SUCCESS))
        print(report)
        
        print(f"\n{colorize('To execute these operations for real, run without the --simulate flag.', TermColors.SIM)}")
    else:
        print(f"\n{stars}")
        print("SIMULATION COMPLETE - NO CHANGES WERE MADE")
        print(f"{stars}\n")
        
        print("The following operations would have been performed:")
        print(report)
        
        print("\nTo execute these operations for real, run without the --simulate flag.")


def main() -> int:
    """
    Main function.
    
    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    try:
        args = parse_arguments()
        
        # Set up logging
        setup_logging(args.debug)
        
        # Create the command runner with appropriate simulation mode
        cmd_runner = CommandRunner(
            SimulationMode.SIMULATE if args.simulate else SimulationMode.DISABLED,
            not args.no_color
        )
        
        # Configure disk simulation parameters if in simulation mode
        if args.simulate:
            logger.info("Running in simulation mode - NO CHANGES WILL BE MADE")
            
            # Set disk simulation parameters
            sim_params = {}
            if args.sim_disk_size:
                sim_params["disk_size"] = args.sim_disk_size
                logger.info(f"Simulating disk size: {args.sim_disk_size}")
                
            if args.sim_disk_type:
                sim_params["disk_type"] = args.sim_disk_type
                is_rotational = args.sim_disk_type == "hdd"
                is_nvme = args.sim_disk_type == "nvme"
                sim_params["rotational"] = is_rotational
                sim_params["nvme"] = is_nvme
                logger.info(f"Simulating disk type: {args.sim_disk_type} (rotational: {is_rotational})")
                
            if args.sim_disk_trim:
                sim_params["trim_supported"] = args.sim_disk_trim == "yes"
                logger.info(f"Simulating TRIM support: {args.sim_disk_trim}")
                
            cmd_runner.set_simulation_params(sim_params)
            cmd_runner.use_real_disk_info = args.sim_use_real
            
            if args.sim_use_real:
                logger.info("Using characteristics of real disk even in simulation mode")
        
        # Check prerequisites
        try:
            # Pass the use_real_disk_info flag to check_prerequisites
            check_prerequisites(cmd_runner, args.sim_use_real if args.simulate else False)
        except RuntimeError as e:
            logger.error(str(e))
            return 1
            
        # Normalize encryption arguments
        normalize_encryption_args(args)
        
        # Validate encryption requirements
        try:
            validate_encryption_requirements(args, cmd_runner)
        except EncryptionError as e:
            logger.error(str(e))
            return 1
            
        # Get disk info
        try:
            disk_info = get_disk_info(args.disk, cmd_runner)
            
            # Force TRIM support if requested and disk is SSD
            if args.force_discard and not disk_info["rotational"]:
                logger.info("Forcing TRIM/discard support as requested by --force-discard")
                disk_info["trim_supported"] = True
                
        except DiskNotFoundError as e:
            logger.error(str(e))
            return 1
            
        # Log disk information
        logger.info(f"Disk: {args.disk}")
        logger.info(f"Size: {bytes_to_human_readable(disk_info['size_bytes'])}")
        logger.info(f"Type: {'SSD/NVMe' if not disk_info['rotational'] else 'HDD'}")
        logger.info(f"NVMe: {'Yes' if disk_info['nvme'] else 'No'}")
        logger.info(f"Model: {disk_info.get('model', 'Unknown')}")
        if not disk_info["rotational"]:
            logger.info(f"TRIM support: {'Yes' if disk_info.get('trim_supported', False) else 'Not detected'}")
        logger.info("")
        
        # Execute main workflow
        try:
            # CHANGEMENT: Si reset Opal est nécessaire, le faire avant de préparer le disque
            if (args.hardware_encryption and 
                isinstance(args.hardware_encryption, tuple) and 
                len(args.hardware_encryption) >= 1 and 
                args.hardware_encryption[0] and 
                args.hardware_encryption[0].lower() != "none"):
                from architect.core.encryption import reset_opal_drive
                logger.info("OPAL reset with PSID requested, performing reset before disk preparation")
                reset_opal_drive(args.disk, args.hardware_encryption[0], cmd_runner)
            
            # Prepare the disk
            partitions = prepare_disk(args.disk, disk_info, args, cmd_runner)
            
            # Set up encryption if requested
            if args.hardware_encryption or args.software_encryption:
                partitions = setup_encryption(args.disk, partitions, args, cmd_runner)
            
            # Create filesystems
            create_filesystems(partitions, disk_info, args, cmd_runner)
            
            # Create btrfs subvolumes
            create_btrfs_subvolumes(partitions, args, cmd_runner)
            
            # Determine mount options
            mount_options = determine_mount_options(disk_info, args)
            
            # Mount filesystems
            mount_filesystems(partitions, mount_options, args, cmd_runner)
            
            # Generate fstab
            generate_fstab(partitions, mount_options, args, cmd_runner)
            
            # Generate crypttab if encryption is used
            generate_crypttab(partitions, disk_info, args, cmd_runner)
            
            if args.simulate:
                display_simulation_summary(args, cmd_runner)
            else:
                logger.info("Disk preparation completed successfully")
                logger.info(f"The system is mounted at {args.target}")
                
                if args.hardened:
                    logger.info("")
                    logger.info("NOTE: Hardened mount options have been applied according to ANSSI recommendations")
                    logger.info("      This includes noexec on /var which may require adjustments for package management")
                    logger.info("      and certain administrative operations")
            
            return 0
            
        except (NotEnoughSpaceError, PartitioningError, EncryptionError, 
                FilesystemError, MountError, FstabError, CrypttabError) as e:
            logger.error(str(e))
            return 1
    
    except KeyboardInterrupt:
        logger.error("Operation cancelled by user")
        return 130
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        if 'args' in locals() and args.debug:
            import traceback
            traceback.print_exc()
        return 1


# For module import compatibility
if __name__ == "__main__":
    # Use argparse's built-in help option (-h/--help)
    sys.exit(main())
