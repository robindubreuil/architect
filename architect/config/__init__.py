"""
Configuration file generation for the target system.

This module provides common utilities for generating configuration files.
"""
import logging
from pathlib import Path
from typing import Optional

from architect.utils.command import CommandRunner, SimulationMode

logger = logging.getLogger('architect')


def create_directory(
    path: Path, 
    cmd_runner: CommandRunner, 
    description: Optional[str] = None
) -> None:
    """
    Create a directory if it doesn't exist or log that it would be created in simulation mode.
    
    Args:
        path: Directory path to create
        cmd_runner: CommandRunner instance for executing commands
        description: Optional description of the directory for logging
    """
    desc = f"{description} " if description else ""
    
    if cmd_runner.simulation_mode == SimulationMode.SIMULATE:
        logger.info(f"Would create {desc}directory: {path}")
    else:
        path.mkdir(exist_ok=True, parents=True)
        logger.debug(f"Created {desc}directory: {path}")


def create_etc_directory(target_path: Path, cmd_runner: CommandRunner) -> None:
    """
    Create the /etc directory in the target if it doesn't exist.
    
    Args:
        target_path: Path to the target directory
        cmd_runner: CommandRunner instance for executing commands
    """
    etc_path = target_path / "etc"
    create_directory(etc_path, cmd_runner, "etc")