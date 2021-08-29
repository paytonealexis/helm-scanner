import datetime
import os
import errno
import sys
from collections import defaultdict
import subprocess
import wget
import traceback
import tarfile
import glob
import re
import logging as helmscanner_logging

from helmScanner.collect import artifactHubCrawler
from helmScanner.output import result_writer
from helmScanner.output import s3_uploader
from helmScanner.multithreader import multithreadit
from helmScanner.image_scanner import imageScanner
from helmScanner.scannerTimeStamp import currentRunTimestamp



# Local setup of checkov
from checkov.logging_init import init as logging_init
from checkov.helm.registry import registry
from checkov.helm.runner import Runner as helm_runner

class Runner():

    def __init__(self):
        #self.args = args
        # Checkov logging so we dont default to debug output from checkov.
        logging_init()


        SCAN_TIME = currentRunTimestamp
        RESULTS_PATH = f'{os.path.abspath(os.path.curdir)}/results/{SCAN_TIME}'

        globalDepsUsage = {}
        globalDepsList = defaultdict(list)
        emptylist = []


    def run_helm_scanner(self):

        for directories in ['checks', 'summaries', 'deps', 'containers', 'container_summaries', 'dockerfiles']:
            filename = f"results/{currentRunTimestamp}/{directories}/blah.tmp"
            if not os.path.exists(os.path.dirname(filename)):
                try:
                    os.makedirs(os.path.dirname(filename))
                except OSError as exc: # Guard against race condition
                    if exc.errno != errno.EEXIST:
                        raise

        crawler = artifactHubCrawler.ArtifactHubCrawler()
        crawlDict, totalRepos, totalPackages = crawler.crawl()
        #helmscanner_logging.info(f"Runner: Crawl completed with {totalPackages} charts from {totalRepos} repositories.")

        helmscanner_logging.debug(f"Global deps usage: {self.globalDepsUsage}")
        helmscanner_logging.debug(f"Global deps list {self.globalDepsList}")

        result_writer.print_csv(summary_lst, result_lst, helmdeps_lst, empty_resources, self.RESULTS_PATH, repo['repoName'], orgRepoFilename, globalDepsList, globalDepsUsage)
        #Upload and rename per org, rather than waiting till the end of the run.
        self.uploadResultsPartial()


    def uploadResultsPartial(self):
        if os.environ.get('RESULT_BUCKET'):
            helmscanner_logging.info(f'Uploading results to {os.environ["RESULT_BUCKET"]}')
            s3_uploader.upload_results(self.RESULTS_PATH, self.SCAN_TIME, True)
