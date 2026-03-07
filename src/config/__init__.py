"""
Configuration package
Contains all configuration settings and environment variables.
"""

from .settings import *

__all__ = [
    'API_KEY',
    'API_SECRET', 
    'DEMO_API_KEY',
    'DEMO_API_SECRET',
    'TESTNET',
    'BOT_TOKEN',
    'CHANNEL_ID',
    'SUPABASE_URL',
    'SUPABASE_KEY',
    'MIN_VOLUME',
    'MAX_VOLUME',
    'THRESHOLD',
    'TIME_WINDOW',
    'TP_LEVELS',
    'SL_LEVELS'
]