"""
Command execution utilities.

This module provides tools for executing shell commands with simulation support.
"""
import logging
import os
import re
import subprocess
import uuid
from enum import Enum
from typing import Dict, List, Optional, Union, Any, Set

logger = logging.getLogger('architect')

# ANSI Colors for enhanced terminal output
class TermColors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


class SimulationMode(Enum):
    """Enumeration for simulation modes"""
    DISABLED = 0  # Normal operation
    SIMULATE = 1  # Simulate operations


class CommandRunner:
    """
    Class responsible for command execution with simulation support.
    Acts as a wrapper around subprocess.run with additional functionality.
    """
    def __init__(self, simulation_mode: SimulationMode, colored_output: bool = True):
        """
        Initialize the command runner.
        
        Args:
            simulation_mode: Simulation mode to operate in
            colored_output: Whether to use colored output in terminal
        """
        self.simulation_mode = simulation_mode
        self.colored_output = colored_output
        self.commands_run: List[Dict[str, Any]] = []
        
        # Generate a unique simulation ID
        self.simulation_id = str(uuid.uuid4())[:8]
        
        # Keep track of simulated devices/UUIDs
        self.simulated_uuids = {}
        self.simulated_partuuids = {}
        self.simulated_devices = set()
        self.output_handlers = {}
        
        # Simulation parameters
        self.simulation_params = {}
        self.use_real_disk_info = False
        
        # Bind command types to handlers
        self._bind_output_handlers()

    def set_simulation_params(self, params: Dict[str, Any]) -> None:
        """
        Set parameters for disk simulation.
        
        Args:
            params: Dictionary of simulation parameters
        """
        self.simulation_params = params

    def _bind_output_handlers(self) -> None:
        """Bind command types to output handlers for simulation"""
        # Maps command prefixes to handler functions
        self.output_handlers = {
            "blkid": self._handle_blkid_output,
            "blockdev": self._handle_blockdev_output,
            "lsblk": self._handle_lsblk_output,
            "cryptsetup": self._handle_cryptsetup_output,
        }

    def run(self, cmd: List[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
        """
        Run a shell command or simulate running it.
        
        Args:
            cmd: Command to run as list of strings
            check: Whether to check for non-zero return code
            **kwargs: Additional arguments to pass to subprocess.run
            
        Returns:
            CompletedProcess instance from subprocess.run
        """
        cmd_str = ' '.join(cmd)
        logger.debug(f"Command requested: {cmd_str}")
        
        # Keep track of this command
        cmd_record = {
            "command": cmd.copy(),
            "timestamp": None,
            "success": None,
            "simulated": self.simulation_mode == SimulationMode.SIMULATE
        }
        
        # For simulation mode
        if self.simulation_mode == SimulationMode.SIMULATE:
            if self.colored_output:
                sim_prefix = f"{TermColors.CYAN}[SIM:{self.simulation_id}]{TermColors.ENDC}"
            else:
                sim_prefix = f"[SIM:{self.simulation_id}]"
                
            logger.info(f"{sim_prefix} Would execute: {cmd_str}")
            
            # Create a simulated completed process
            result = self._simulate_command_output(cmd, **kwargs)
            cmd_record["success"] = True
            self.commands_run.append(cmd_record)
            return result
            
        # For real execution mode
        try:
            result = subprocess.run(
                cmd,
                check=check,
                text=True,
                capture_output=True,
                **kwargs
            )
            cmd_record["success"] = True
            self.commands_run.append(cmd_record)
            return result
            
        except subprocess.CalledProcessError as e:
            cmd_record["success"] = False
            self.commands_run.append(cmd_record)
            logger.error(f"Command failed: {cmd_str}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"Stdout: {e.stdout}")
            logger.error(f"Stderr: {e.stderr}")
            raise

    def _simulate_command_output(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """
        Generate simulated output for a command.
        
        Args:
            cmd: Command to simulate
            **kwargs: Additional arguments passed to the original command
            
        Returns:
            CompletedProcess with simulated output
        """
        # Create a base result with empty output
        result = subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="",
            stderr=""
        )
        
        # Check if we have a specific handler for this command
        cmd_name = cmd[0] if cmd else ""
        for prefix, handler in self.output_handlers.items():
            if cmd_name.endswith(prefix):
                return handler(cmd, result, **kwargs)
        
        # Default handling for other commands
        return result

    def run_real(self, cmd: List[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
        """
        Run a shell command for real, even in simulation mode.
        This is useful for querying real disk information while simulating operations.
        
        Args:
            cmd: Command to run as list of strings
            check: Whether to check for non-zero return code
            **kwargs: Additional arguments to pass to subprocess.run
            
        Returns:
            CompletedProcess instance from subprocess.run
        """
        cmd_str = ' '.join(cmd)
        logger.debug(f"Running real command: {cmd_str}")
        
        # Execute the command for real
        try:
            result = subprocess.run(
                cmd,
                check=check,
                text=True,
                capture_output=True,
                **kwargs
            )
            return result
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Real command failed: {cmd_str}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"Stdout: {e.stdout}")
            logger.error(f"Stderr: {e.stderr}")
            raise
            
    def _handle_blkid_output(self, cmd: List[str], result: subprocess.CompletedProcess, **kwargs) -> subprocess.CompletedProcess:
        """
        Simulate blkid command output.
        
        Args:
            cmd: The blkid command
            result: Base CompletedProcess to modify
            
        Returns:
            CompletedProcess with simulated blkid output
        """
        try:
            if "-s" in cmd and len(cmd) > cmd.index("-s") + 1:
                param_type = cmd[cmd.index("-s") + 1]
                device_path = cmd[-1]
                
                # Generate UUID or PARTUUID based on request
                if param_type == "UUID":
                    # Generate consistent UUID for the same device
                    if device_path not in self.simulated_uuids:
                        self.simulated_uuids[device_path] = str(uuid.uuid4())
                    
                    result.stdout = self.simulated_uuids[device_path] + "\n"
                    
                elif param_type == "PARTUUID":
                    # Generate consistent PARTUUID for the same device
                    if device_path not in self.simulated_partuuids:
                        self.simulated_partuuids[device_path] = str(uuid.uuid4())
                    
                    result.stdout = self.simulated_partuuids[device_path] + "\n"
        except Exception:
            # In case of any error, return generic UUID
            result.stdout = str(uuid.uuid4()) + "\n"
            
        return result

    def _handle_blockdev_output(self, cmd: List[str], result: subprocess.CompletedProcess, **kwargs) -> subprocess.CompletedProcess:
        """
        Simulate blockdev command output.
        
        Args:
            cmd: The blockdev command
            result: Base CompletedProcess to modify
            
        Returns:
            CompletedProcess with simulated blockdev output
        """
        if "--getsize64" in cmd:
            # Check if we have a disk size parameter
            if "disk_size" in self.simulation_params:
                # Try to parse the size
                import re
                from architect.utils.format import parse_size_spec
                
                size_spec = self.simulation_params["disk_size"]
                # Estimation de la taille totale pour le parsing
                total_size = 10 * 1024**4  # 10 TiB comme référence
                try:
                    size_bytes = parse_size_spec(size_spec, total_size)
                    result.stdout = f"{size_bytes}\n"
                except ValueError:
                    # Fallback to default size
                    result.stdout = "500107862016\n"  # ~465.76 GiB
            else:
                # Default: Simulate 500GB disk
                result.stdout = "500107862016\n"
        
        return result

    def _handle_lsblk_output(self, cmd: List[str], result: subprocess.CompletedProcess, **kwargs) -> subprocess.CompletedProcess:
        """
        Simulate lsblk command output.
        
        Args:
            cmd: The lsblk command
            result: Base CompletedProcess to modify
            
        Returns:
            CompletedProcess with simulated lsblk output
        """
        # If checking disk type
        if "-o" in cmd and "TYPE" in cmd[cmd.index("-o") + 1]:
            result.stdout = "disk\n"
        # If checking disk model
        elif "-o" in cmd and "MODEL" in cmd[cmd.index("-o") + 1]:
            if "disk_type" in self.simulation_params:
                disk_type = self.simulation_params["disk_type"].upper()
                result.stdout = f"SIMULATED {disk_type} DISK\n"
            else:
                result.stdout = "SIMULATED DISK\n"
        
        return result

    def _handle_cryptsetup_output(self, cmd: List[str], result: subprocess.CompletedProcess, **kwargs) -> subprocess.CompletedProcess:
        """
        Simulate cryptsetup command output.
        
        Args:
            cmd: The cryptsetup command
            result: Base CompletedProcess to modify
            
        Returns:
            CompletedProcess with simulated cryptsetup output
        """
        if "--version" in cmd:
            result.stdout = "cryptsetup 2.6.1\n"
        
        return result

    def get_simulation_report(self) -> str:
        """
        Generate a report of all simulated commands.
        
        Returns:
            Formatted string with report of simulated commands
        """
        if self.simulation_mode != SimulationMode.SIMULATE:
            return "Simulation mode is not active."
        
        report = []
        report.append("=" * 80)
        report.append(f"SIMULATION REPORT [ID: {self.simulation_id}]")
        report.append("=" * 80)
        report.append("")
        
        # Group commands by type
        command_groups = {}
        for cmd_record in self.commands_run:
            cmd = cmd_record["command"]
            cmd_type = cmd[0] if cmd else "unknown"
            
            if cmd_type not in command_groups:
                command_groups[cmd_type] = []
            
            command_groups[cmd_type].append(cmd_record)
        
        # Report by command type
        for cmd_type, cmd_records in command_groups.items():
            report.append(f"{cmd_type.upper()} COMMANDS:")
            report.append("-" * 40)
            
            for i, cmd_record in enumerate(cmd_records, 1):
                cmd = cmd_record["command"]
                cmd_str = ' '.join(cmd)
                report.append(f"{i}. {cmd_str}")
            
            report.append("")
        
        # Summary
        report.append("-" * 80)
        report.append(f"Total commands simulated: {len(self.commands_run)}")
        report.append("=" * 80)
        
        return "\n".join(report)
