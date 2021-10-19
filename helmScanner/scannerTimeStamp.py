"""
Timestamp for helm-scanner
==========================

Creates a timestamp at init, always gives back the same timestamp within a given run.
Used for output of S3 directory structure, and inside CSV's outputs where records 
need assigning to a given run of helm-scanner.

"""

from datetime import datetime
import os
from helmScanner.utils.getArgs import args

if args.timestamp != "NONE":
    helmScannerArtifactTimestamp = str(args.timestamp)
else:
    helmScannerArtifactTimestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

RESULTS_PATH = f'{os.path.abspath(os.path.curdir)}/results/{helmScannerArtifactTimestamp}'

def currentRunTimestamp():
    return helmScannerArtifactTimestamp

def currentRunResultsPath():
    return RESULTS_PATH

currentRunTimestamp = currentRunTimestamp()
currentRunResultsPath = currentRunResultsPath()
