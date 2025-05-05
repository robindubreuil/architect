"""
Base exceptions for architect.

This module defines the hierarchy of exceptions used by architect.
"""

class ArchitectError(Exception):
    """Base exception for Architect errors"""
    pass


class DiskNotFoundError(ArchitectError):
    """Exception raised when specified disk is not found"""
    pass


class NotEnoughSpaceError(ArchitectError):
    """Exception raised when there's not enough space for partitioning"""
    pass


class PartitioningError(ArchitectError):
    """Exception raised when there's an error in partitioning"""
    pass


class EncryptionError(ArchitectError):
    """Exception raised when there's an error in encryption setup"""
    pass


class FilesystemError(ArchitectError):
    """Exception raised when there's an error in filesystem creation"""
    pass


class MountError(ArchitectError):
    """Exception raised when there's an error in mounting"""
    pass


class FstabError(ArchitectError):
    """Exception raised when there's an error in fstab generation"""
    pass


class CrypttabError(ArchitectError):
    """Exception raised when there's an error in crypttab generation"""
    pass
