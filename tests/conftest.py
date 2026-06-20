import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "simulation"))
sys.path.insert(0, str(root / "integration_layer"))
sys.path.insert(0, str(root / "integration"))


def load_service(name: str, service_dir: str):
    path = root / service_dir / "main.py"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
