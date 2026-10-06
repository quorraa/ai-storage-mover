import sys
from ai_storage_mover.gui import main
if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    import tkinter as tk
    from ai_storage_mover.gui import Wizard
    from ai_storage_mover.model import atomic_json
    root = tk.Tk()
    root.withdraw()
    app = Wizard(root)
    root.update_idletasks()
    atomic_json(sys.argv[2], {'desktop': 'passed', 'tk': tk.TkVersion, 'first_page': app.page})
    root.destroy()
else:
    main()
