"""Double-click source launcher; the Windows download includes Python itself."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from ai_storage_mover.gui import main
main()
