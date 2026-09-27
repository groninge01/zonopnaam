"""Import the independent API without starting Home Assistant."""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
package = types.ModuleType("zonopnaam_test")
package.__path__ = [str(ROOT / "custom_components/zonopnaam")]
sys.modules[package.__name__] = package
