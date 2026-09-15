"""Native Hermes dashboard entry; no patches to the Hermes core."""
import importlib.util, sys
from pathlib import Path

package = '_hermes_ryzeapi_dashboard'
root = Path(__file__).resolve().parent.parent
if package not in sys.modules:
    spec = importlib.util.spec_from_file_location(package, root / '__init__.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
router = sys.modules[package].__dict__.get('_dashboard_router')
if router is None:
    from importlib import import_module
    router = import_module(package+'.management').router
    sys.modules[package]._dashboard_router = router
