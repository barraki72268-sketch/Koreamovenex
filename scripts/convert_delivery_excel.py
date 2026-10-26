"""Command-line entry point for the new Excel format."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ectlab.delivery_excel import main
if __name__ == '__main__':
    main()
