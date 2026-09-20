"""Example backend test script.

This script demonstrates how to create a manual backend test.
It can be run through the /tests/manual/example endpoint.
"""

from loguru import logger
from devtools import debug

print("🚀 Test backend - Hello World!")

logger.info("✅ Loguru test: informational message from example.py")
logger.debug("🔍 This is a debug message")
logger.warning("⚠️ This is a warning")

# Simulate a basic test.
def test_simple():
    """Run a basic test function."""
    result = 2 + 2
    assert result == 4, "The calculation should be correct"
    logger.success(f"✅ Simple test passed: 2 + 2 = {result}")
    debug(result)
    
    return result


logger.info("🧪 Starting manual backend tests")
    
try:
    test_simple()
    logger.success("🎉 All tests passed!")
except Exception as e:
    logger.error(f"❌ Error during the test: {e}")
    raise
