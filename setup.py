from cx_Freeze import setup, Executable

# Dependencies are automatically detected, but it might need
# fine tuning.
buildOptions = dict(packages = [], excludes = [])

base = 'Console'

executables = [
    Executable('thingy_grabber.py', base=base)
]


# Usage: python setup.py build
setup(name='Thingy Grabber',
      version = '0.6.2',
      description = 'Thingiverse Grabber',
      options = dict(build_exe = buildOptions),
      executables = executables, requires=['py7zr', 'requests'])
