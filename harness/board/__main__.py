import sys
from harness.board.serve import serve

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
serve(port=port)
