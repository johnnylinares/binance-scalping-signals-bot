#!/usr/bin/env python3
"""
Entry point for the Binance Scalping Signals Bot
"""

import sys
import os

# Add src directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from core.main import main

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())