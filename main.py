#from typing_extensions import required
from helmScanner.runner import Runner

if __name__ == "__main__":
   runner = Runner()
   runner.run_helm_scanner()