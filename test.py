import sys
import a2a

print(f"Python version: {sys.version}")
print(f"a2a version: {getattr(a2a, '__version__', 'unknown')}")
print(f"\na2a contents:\n{dir(a2a)}")
print(f"\na2a.server contents:\n{dir(a2a.server)}")

# List all files in the a2a package
import os
a2a_path = os.path.dirname(a2a.__file__)
print(f"\na2a installation path: {a2a_path}")
for root, dirs, files in os.walk(a2a_path):
    level = root.replace(a2a_path, '').count(os.sep)
    indent = ' ' * 2 * level
    print(f'{indent}{os.path.basename(root)}/')
    subindent = ' ' * 2 * (level + 1)
    for file in files:
        if file.endswith('.py'):
            print(f'{subindent}{file}')