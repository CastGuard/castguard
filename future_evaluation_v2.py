"""Compatibility entry point for the current future-evaluation validator.

Both public filenames execute revision 3. Historical sources live in legacy/.
"""
from future_evaluation_core import *  # preserve the schema-1 import interface

if __name__ == '__main__':
    raise SystemExit(main())
