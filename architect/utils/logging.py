"""
Logging configuration utilities.

This module provides functions for setting up and configuring logging.
"""
import logging
from typing import Optional


def setup_logging(debug: bool = False) -> None:
    """
    Configure logging for the application.
    
    Args:
        debug: Whether to enable debug logging
    """
    level = logging.DEBUG if debug else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger = logging.getLogger('architect')
    logger.setLevel(level)
