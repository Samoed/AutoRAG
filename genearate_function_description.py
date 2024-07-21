import importlib
import inspect
import json
import pkgutil
import re
from typing import Dict, Any, List


def get_params_string(docstring: str) -> list[dict[str, str]]:
    docstring = docstring.split(":return:")[0]
    parts = re.split(r'(:param\s+\w+:)', docstring)
    return_parts = []
    for i in range(len(parts)):
        if parts[i].startswith(":param"):
            _, param_name = parts[i].split()
            param_name = param_name.replace(":", "")
            return_parts.append({
                "name": param_name,
                "description": parts[i + 1].strip(),
            })
            i += 1
    return return_parts


def extract_function_info(func: callable, class_name: str = None) -> Dict[str, Any]:
    """
    Extract information from a callable function or method.
    """
    function_name = func.__name__
    if class_name:
        function_name = f"{class_name}.{function_name}"
    module_name = func.__module__

    # Get signature
    try:
        signature = inspect.signature(func)
    except ValueError:
        # Some functions don't support introspection
        return {
            "function": function_name,
            "module": module_name,
            "error": "Unable to inspect function"
        }

    # Extract parameters
    params = []
    for name, param in signature.parameters.items():
        param_info = {
            "name": name,
            "param_type": str(param.annotation) if param.annotation != inspect.Parameter.empty else "Any",
            "description": ""
        }
        params.append(param_info)

    # Get return type
    return_type = str(signature.return_annotation) if signature.return_annotation != inspect.Signature.empty else "Any"

    # Extract docstring
    docstring = inspect.getdoc(func)
    if docstring:
        # Parse docstring to extract parameter descriptions
        docstring_params = get_params_string(docstring)
        for doc_param in docstring_params:
            for param in params:
                if param['name'] == doc_param["name"]:
                    param['description'] = doc_param["description"]
                    break

    return {
        "function": function_name,
        "module": module_name,
        "params": params,
        "return_type": return_type,
        "docstring": docstring
    }


def is_function_or_method(obj: Any) -> bool:
    """
    Check if an object is a function or method.
    """
    return inspect.isfunction(obj) or inspect.ismethod(obj) or inspect.isbuiltin(obj)


def extract_library_functions(library_name: str) -> List[Dict[str, Any]]:
    """
    Extract information about all functions in a library, excluding third-party and core Python modules.
    """
    functions_info = []

    def explore_module(module):
        for name, obj in inspect.getmembers(module):
            if is_function_or_method(obj) and obj.__module__.startswith(library_name):
                functions_info.append(extract_function_info(obj))
            elif inspect.isclass(obj) and obj.__module__.startswith(library_name):
                # Explore methods of the class
                for method_name, method_obj in inspect.getmembers(obj):
                    # Lazy init have module None
                    if is_function_or_method(
                            method_obj) and method_obj.__module__ is not None and method_obj.__module__.startswith(
                        library_name):
                        functions_info.append(extract_function_info(method_obj, class_name=obj.__name__))

    # Import the library
    library = importlib.import_module(library_name)

    # Explore the main module
    explore_module(library)

    # Explore submodules
    if hasattr(library, '__path__'):
        for _, submodule_name, _ in pkgutil.walk_packages(library.__path__, library.__name__ + '.'):
            try:
                submodule = importlib.import_module(submodule_name)
                explore_module(submodule)
            except ImportError as e:
                print(f"Error importing {submodule_name}: {e}")

    return functions_info


def library_functions_to_json(library_name: str, output_file: str) -> None:
    """
    Extract function information from a library and save to a JSON file.
    """
    functions_info = extract_library_functions(library_name)
    with open(output_file, 'w') as f:
        json.dump(functions_info, f, indent=2)
    print(f"Function information for {library_name} has been saved to {output_file}")

# Example usage
if __name__ == "__main__":
    # import sys
    #
    # if len(sys.argv) != 3:
    #     print("Usage: python script_name.py <library_name> <output_file>")
    #     sys.exit(1)
    #
    # library_name = sys.argv[1]
    # output_file = sys.argv[2]
    library_functions_to_json("autorag", "docs.json")
