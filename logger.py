"""
DevMesh Logging Module
----------------------
Structured logging with file and console output.
Replaces scattered print() statements.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


class ColoredFormatter(logging.Formatter):
    """Terminal output with color codes."""
    
    COLORS = {
        'DEBUG':    '\033[36m',    # Cyan
        'INFO':     '\033[32m',    # Green
        'WARNING':  '\033[33m',    # Yellow
        'ERROR':    '\033[31m',    # Red
        'CRITICAL': '\033[91m',    # Bright Red
        'RESET':    '\033[0m',
    }
    
    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        color = self.COLORS.get(levelname, '')
        reset = self.COLORS['RESET']
        
        # Format: [HH:MM:SS] [LEVEL] [module] message
        ts = datetime.now().strftime("%H:%M:%S")
        msg = f"[{ts}] {color}[{levelname:8s}]{reset} [{record.name}] {record.getMessage()}"
        return msg


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[str] = None,
    name: str = "devmesh"
) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for file logging
        name: Logger name/module
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(ColoredFormatter())
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, mode='a')
        file_formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module."""
    return logging.getLogger(f"devmesh.{name}")
