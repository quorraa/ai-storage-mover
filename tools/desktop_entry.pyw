import sys
from ai_storage_mover.gui import main
if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
    main(self_test=sys.argv[2])
else:
    main()
