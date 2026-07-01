import pkgutil
import importlib
import inspect

__all__ = []

for finder, name, is_pkg in pkgutil.walk_packages(__path__, __name__ + "."):
    module = importlib.import_module(name)

    for attr_name, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ == name:
            globals()[attr_name] = obj
            __all__.append(attr_name)
