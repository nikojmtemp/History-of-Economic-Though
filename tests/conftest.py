"""Tests never touch the player's real saves: everything goes to a scratch folder."""

import os
import tempfile

os.environ["STOCK_SAVES"] = tempfile.mkdtemp(prefix="stock-test-saves-")
